import select
import asyncio
import os
from uuid import uuid4
import mimetypes
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi import (
    APIRouter,
    Depends,
    Form,
    UploadFile,
    File,
    HTTPException,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, update
from urllib.parse import urlparse
from typing import Tuple

from ...core import auth
from ...core.database import get_db
from .models import Invoice
from . import schemas as invoices_schemas
from . import crud as invoices_crud
from ..batches import crud as batches_crud
from ..retraining_model.data_processor import process_with_qwen
from ..users import models as users_models
from ...utils.ocr_parser import process_invoice
from ...utils.r2 import (
    upload_to_r2_bytes,
    get_file_from_r2,
    s3,
    R2_BUCKET,
)
from .models import Invoice
from .schemas import InvoiceDeleteRequest
from ...utils.files_service import (
    upload_to_files_service_bytes,
    get_file_from_files_service,
)

USE_CLOUD_STORAGE = True

router = APIRouter(prefix="/invoice", tags=["invoices"])

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)


async def get_current_user(current_user=Depends(auth.get_current_user)):
    return current_user


def parse_range(range_str: str) -> Tuple[int, int] | dict:
    """
    Parses a string like '1-50' into (start, end)
    Returns dict with error if invalid
    """
    try:
        start_str, end_str = range_str.split("-")
        start, end = int(start_str), int(end_str)
        if start < 1 or end < start:
            raise ValueError()
        return start, end
    except Exception:
        return {
            "ok": False,
            "message": "Invalid range format. Use start-end, e.g., 1-50.",
        }


@router.get("/analytics")
async def get_invoice_analytics(
    current_user: users_models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        data = await invoices_crud.get_invoice_analytics(
            db, current_user.effective_user_id
        )
        return {"ok": True, "message": "Analytics fetched successfully", "data": data}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/extract/{invoice_type}")
async def extract_invoice(
    invoice_type: str,
    file: UploadFile = File(...),
    file_hash: str = Form(None),
    is_duplicate: bool = Form(False),
    current_user: users_models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ext = os.path.splitext(file.filename)[1]
    safe_name = f"{uuid4().hex}{ext}"
    content = await file.read()
    placeholder_invoice = await invoices_crud.create_processing_invoice(
        db=db,
        owner_id=current_user.effective_user_id,
        vendor_name=file.filename,
        invoice_type=invoice_type,
    )

    if USE_CLOUD_STORAGE:
        file_url = await asyncio.to_thread(upload_to_r2_bytes, content, safe_name)
    else:
        file_url = await asyncio.to_thread(
            upload_to_files_service_bytes, content, safe_name
        )

    placeholder_invoice.file_path = file_url
    await db.commit()
    await db.refresh(placeholder_invoice)

    asyncio.create_task(
        invoices_crud.run_invoice_extraction(
            invoice_id=placeholder_invoice.id,
            content=content,
            ext=ext,
            invoice_type=invoice_type,
            file_url=file_url,
            file_hash=file_hash,
            is_duplicate=is_duplicate,
        )
    )

    return {
        "ok": True,
        "message": "Upload complete. Extraction started in background.",
        "invoice_id": placeholder_invoice.id,
        "file_location": file_url,
    }


@router.post("/request_review")
async def request_review(
    invoice_id: int,
    current_user: users_models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    invoice = await invoices_crud.get_invoice_by_id_and_owner(
        db, invoice_id, current_user.effective_user_id
    )
    if not invoice:
        raise HTTPException(
            status_code=404, detail={"ok": False, "msg": "Invoice not found"}
        )
    invoice.reviewed = False
    await db.commit()
    return {"ok": True, "msg": "Invoice sent for review", "invoice_id": invoice.id}


@router.post("/review")
async def review_invoice(
    payload: invoices_schemas.ReviewPayload,
    current_user: users_models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    invoice = await invoices_crud.update_invoice_review(
        db,
        payload.invoice_id,
        current_user.effective_user_id,
        payload.reviewed,
        payload.corrected_fields,
    )
    if not invoice:
        raise HTTPException(
            status_code=404, detail={"ok": False, "msg": "Invoice not found"}
        )

    if invoice.reviewed and invoice.invoice_date:
        batch_id = await batches_crud.find_matching_batch_for_invoice(
            db, current_user.effective_user_id, invoice.invoice_date
        )
        if batch_id:
            await db.execute(
                update(Invoice)
                .where(Invoice.id == invoice.id)
                .values(batch_id=batch_id)
            )
            await db.commit()
            print(f"📦 Invoice {invoice.id} auto-assigned to batch {batch_id}")

    return {"ok": True, "msg": "Invoice review updated", "invoice_id": invoice.id}


@router.get(
    "/all/{invoice_type}/{range_str}",
    response_model=invoices_schemas.InvoiceListResponse,
)
async def get_all_invoices_paginated(
    invoice_type: str,
    range_str: str,
    search: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    current_user: users_models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if invoice_type not in {"expense", "sales"}:
        return {"ok": False, "message": "Invalid invoice type"}

    if search or from_date or to_date:
        invoices = await invoices_crud.list_invoices_by_owner(
            db,
            owner_id=current_user.effective_user_id,
            invoice_type=invoice_type,
            search=search,
            from_date=from_date,
            to_date=to_date,
            ignore_pagination=True,
        )
        total_count = len(invoices)
        return {"ok": True, "invoices": invoices, "total_count": total_count}

    parsed = parse_range(range_str)
    if isinstance(parsed, dict):  # error
        return parsed

    start, end = parsed
    limit = end - start + 1
    offset = start - 1

    invoices = await invoices_crud.list_invoices_by_owner(
        db,
        owner_id=current_user.effective_user_id,
        invoice_type=invoice_type,
        limit=limit,
        offset=offset,
    )

    total_stmt = select(func.count(Invoice.id)).where(
        Invoice.owner_id == current_user.effective_user_id,
        Invoice.batch_id.is_(None),
        Invoice.type == invoice_type,
    )
    total_result = await db.execute(total_stmt)
    total_count = total_result.scalar() or 0

    return {"ok": True, "invoices": invoices, "total_count": total_count}


@router.get("/to_be_reviewed", response_model=invoices_schemas.InvoiceTBRListResponse)
async def to_be_reviewed(
    current_user: users_models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    invoices = await invoices_crud.list_invoices_to_review_by_owner(
        db, current_user.effective_user_id
    )
    return {"ok": True, "invoices": invoices}


@router.post("/edit/{invoice_id}")
async def edit_invoice(
    invoice_id: int,
    payload: invoices_schemas.EditInvoiceFields,
    current_user: users_models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    invoice = await invoices_crud.edit_invoice(
        db, invoice_id, current_user.effective_user_id, payload.corrected_fields
    )
    if not invoice:
        raise HTTPException(
            status_code=404, detail={"ok": False, "msg": "Invoice not found"}
        )
    return {"ok": True, "msg": "Invoice updated", "invoice_id": invoice.id}


@router.get("/{invoice_id}", response_model=invoices_schemas.InvoiceOut)
async def get_invoice(
    invoice_id: int,
    current_user: users_models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    invoice = await invoices_crud.get_invoice_by_id_and_owner(
        db, invoice_id, current_user.effective_user_id
    )
    if not invoice:
        raise HTTPException(
            status_code=404, detail="Invoice not found or already reviewed"
        )
    return invoice


@router.get("/file/{invoice_id}")
async def get_invoice_file(
    invoice_id: int,
    current_user: users_models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    invoice = await invoices_crud.get_invoice_by_id_and_owner(
        db, invoice_id, current_user.effective_user_id
    )
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    filename = invoice.file_path.split("/")[-1]
    if USE_CLOUD_STORAGE:
        file_obj = get_file_from_r2(filename)
    else:
        file_obj = get_file_from_files_service(filename)

    if not file_obj:
        raise HTTPException(status_code=500, detail="Failed to fetch file from R2")

    content_type, _ = mimetypes.guess_type(filename)
    if content_type is None:
        content_type = "application/octet-stream"

    return StreamingResponse(file_obj, media_type=content_type)


@router.delete("/delete")
async def delete_invoice(
    payload: InvoiceDeleteRequest,
    current_user: users_models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    invoice_ids = payload.invoice_ids

    if not invoice_ids:
        raise HTTPException(status_code=400, detail="No invoice IDs provided")

    deleted_count = 0
    file_paths_to_remove = []

    for inv_id in invoice_ids:
        inv = None
        acting_id = getattr(current_user, "jwt_acting_user_id", None)

        if getattr(current_user, "jwt_is_accountant", False):
            if acting_id:
                inv = await invoices_crud.get_invoice_by_id_and_owner(
                    db, inv_id, acting_id
                )
            else:
                inv = await invoices_crud.get_invoice_by_id(db, inv_id)
        elif getattr(current_user, "jwt_company_id", None) and getattr(
            current_user, "jwt_company_role", None
        ):
            inv = await invoices_crud.get_invoice_by_id_and_company(
                db, inv_id, current_user.jwt_company_id
            )
        else:
            inv = await invoices_crud.get_invoice_by_id_and_owner(
                db, inv_id, current_user.effective_user_id
            )

        if not inv:
            continue

        if getattr(current_user, "jwt_is_accountant", False):
            success = await invoices_crud.soft_delete_invoice(
                db, inv_id, deleted_by=current_user.effective_user_id
            )
            if success:
                deleted_count += 1
        else:
            if inv.file_path:
                file_paths_to_remove.append(inv.file_path)

            if getattr(current_user, "jwt_is_super_admin", False):
                await db.execute(update(Invoice).where(Invoice.id == inv_id).values())
                await db.delete(inv)
                await db.commit()
                deleted_count += 1
            elif getattr(current_user, "jwt_company_id", None) and getattr(
                current_user, "jwt_company_role", None
            ):
                await db.delete(inv)
                await db.commit()
                deleted_count += 1
            else:
                await invoices_crud.delete_invoices(
                    db, [inv_id], current_user.effective_user_id
                )
                deleted_count += 1

    for path in file_paths_to_remove:
        try:
            parsed = urlparse(path)
            key = parsed.path.lstrip("/")
            s3.delete_object(Bucket=R2_BUCKET, Key=key)
        except Exception as e:
            print(f"Error deleting file from R2 {path}: {e}")

    return {
        "ok": True,
        "msg": f"{deleted_count} invoice(s) deleted",
        "invoice_ids": invoice_ids,
    }


@router.post("/extract-local/{invoice_type}")
async def extract_invoice_local(
    invoice_type: str,
    file: UploadFile = File(...),
    current_user: users_models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):

    ext = os.path.splitext(file.filename)[1]
    safe_name = f"{uuid4().hex}_{invoice_type}_local{ext}"
    content = await file.read()
    loop = asyncio.get_event_loop()

    parsed_fields = await loop.run_in_executor(
        None, process_with_qwen, content, ext, invoice_type
    )
    if USE_CLOUD_STORAGE:
        file_url = await asyncio.to_thread(upload_to_r2_bytes, content, safe_name)
    else:
        file_url = await asyncio.to_thread(
            upload_to_files_service_bytes, content, safe_name
        )

    field_values = [
        parsed_fields.get("vendor_name"),
        parsed_fields.get("invoice_number"),
        parsed_fields.get("invoice_date"),
        parsed_fields.get("trn_vat_number"),
        parsed_fields.get("before_tax_amount"),
        parsed_fields.get("tax_amount"),
        parsed_fields.get("total"),
    ]

    all_null = all(v in [None, ""] for v in field_values)

    if all_null:
        return {
            "ok": False,
            "msg": f"{invoice_type.capitalize()} parsing failed, upload the document again",
            "parsed_fields": parsed_fields,
            "file_location": file_url,
        }

    parsed_fields["type"] = invoice_type

    invoice = await invoices_crud.create_invoice(
        db, current_user.effective_user_id, file_url, parsed_fields
    )

    return {
        "ok": True,
        "msg": f"{invoice_type.capitalize()} uploaded and parsed successfully (local mode)",
        "invoice_id": invoice.id,
        "parsed_fields": parsed_fields,
        "file_location": file_url,
    }


@router.post("/check-duplicate")
async def check_duplicate(
    payload: invoices_schemas.HashCheckRequest,
    current_user: users_models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    file_hash = payload.file_hash.lower()

    stmt = select(Invoice).where(
        Invoice.owner_id == current_user.effective_user_id,
        Invoice.file_hash == file_hash,
    )
    result = await db.execute(stmt)
    existing_invoice = result.scalars().first()

    if existing_invoice:
        return JSONResponse(
            {
                "is_duplicate": True,
                "existing_invoice_id": existing_invoice.id,
                "message": "Duplicate file found",
            }
        )

    return JSONResponse({"is_duplicate": False, "existing_invoice_id": None})


@router.post("/push_to_qb/{invoice_id}")
async def push_invoice(
    invoice_id: int,
    current_user: users_models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    invoice = await invoices_crud.get_invoice_by_id_and_owner(
        db, invoice_id, current_user.effective_user_id
    )
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    if not invoice.verified:
        raise HTTPException(status_code=400, detail="Invoice not verified")

    invoice_payload = {
        "Line": [
            {
                "Amount": float(invoice.total),
                "DetailType": "SalesItemLineDetail",
                "SalesItemLineDetail": {
                    "ItemRef": {
                        "value": "1",
                        "name": "Services",
                    }
                },
            }
        ],
        "CustomerRef": {"value": "1"},
        "TxnDate": str(invoice.invoice_date),
        "PrivateNote": f"Invoice {invoice.id} from website",
    }

    try:
        qb_response = push_invoice_to_qb(invoice_payload)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    invoice.qb_invoice_id = qb_response.get("Invoice", {}).get("Id")
    await db.commit()

    return {
        "ok": True,
        "message": "Invoice pushed to QuickBooks",
        "qb_invoice_id": invoice.qb_invoice_id,
    }


@router.post("/retry_extraction/{invoice_id}")
async def retry_extraction(
    invoice_id: int,
    current_user: users_models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    invoice = await invoices_crud.get_invoice_by_id_and_owner(
        db, invoice_id, current_user.effective_user_id
    )
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    if not invoice.file_path:
        raise HTTPException(status_code=400, detail="Invoice file missing")

    invoice.is_processing = True
    invoice.extraction_status = "pending"
    await db.commit()

    filename = invoice.file_path.split("/")[-1]
    if USE_CLOUD_STORAGE:
        file_obj = get_file_from_r2(filename)
    else:
        file_obj = get_file_from_files_service(filename)

    if not file_obj:
        await invoices_crud.mark_invoice_failed(db, invoice_id)
        raise HTTPException(status_code=500, detail="Failed to fetch invoice file")

    content = file_obj.read()
    ext = os.path.splitext(filename)[1]

    loop = asyncio.get_event_loop()
    parsed_fields = await loop.run_in_executor(
        None, process_invoice, content, ext, invoice.type
    )

    field_values = [
        parsed_fields.get("vendor_name"),
        parsed_fields.get("invoice_number"),
        parsed_fields.get("invoice_date"),
        parsed_fields.get("trn_vat_number"),
        parsed_fields.get("before_tax_amount"),
        parsed_fields.get("tax_amount"),
        parsed_fields.get("total"),
    ]
    all_null = all(v in [None, ""] for v in field_values)

    if all_null:
        await invoices_crud.mark_invoice_failed(db, invoice_id)
        return {"ok": False, "msg": "Retry failed — extraction produced no fields"}

    updated = await invoices_crud.retry_invoice_extraction(
        db, invoice_id, parsed_fields
    )
    return {
        "ok": True,
        "msg": "Invoice extraction retried successfully",
        "invoice_id": updated.id,
        "parsed_fields": parsed_fields,
    }
