import shutil
import asyncio
import os
from uuid import uuid4
from datetime import datetime
import mimetypes
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import and_, or_
from urllib.parse import urlparse
from typing import Tuple

from ..retraining_model.data_processor import process_with_qwen

from app.core import auth
from ..users import models as users_models
from ..users import crud as users_crud
from . import schemas as invoices_schemas
from . import crud as invoices_crud
from ...core.database import get_db
from ...utils.ocr_parser import process_invoice
from ...utils.r2 import (
    upload_to_r2_bytes,
    get_file_from_r2,
    s3,
    R2_BUCKET,
)
from ...utils.files_service import (
    upload_to_files_service_bytes,
    get_file_from_files_service,
)

USE_CLOUD_STORAGE = True

router = APIRouter(prefix="/invoice", tags=["invoices"])

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)


async def get_current_user(
    token: str = Depends(auth.oauth2_scheme), db: AsyncSession = Depends(get_db)
):
    decoded = auth.decode_token(token)

    if not decoded.get("ok"):
        raise HTTPException(
            status_code=401, detail=decoded.get("error", "Invalid token")
        )

    email = decoded.get("email")

    if not email:
        raise HTTPException(status_code=401, detail="Token missing email")

    user = await users_crud.get_user_by_email(db, email)

    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


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


@router.post("/extract/{invoice_type}")
async def extract_invoice(
    invoice_type: str,
    file: UploadFile = File(...),
    current_user: users_models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ext = os.path.splitext(file.filename)[1]
    safe_name = f"{uuid4().hex}{ext}"
    content = await file.read()

    placeholder_invoice = await invoices_crud.create_processing_invoice(
        db=db,
        owner_id=current_user.id,
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

    loop = asyncio.get_event_loop()
    parsed_fields = await loop.run_in_executor(None, process_invoice, content, ext)

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
        await invoices_crud.mark_invoice_failed(db, placeholder_invoice.id)
        return {
            "ok": False,
            "msg": "Invoice parsing failed, upload the document again",
            "invoice_id": placeholder_invoice.id,
            "parsed_fields": parsed_fields,
            "file_location": file_url,
        }

    parsed_fields["type"] = invoice_type
    updated_invoice = await invoices_crud.update_invoice_after_processing(
        db=db,
        invoice_id=placeholder_invoice.id,
        parsed_fields=parsed_fields,
        file_url=file_url,
    )

    return {
        "ok": True,
        "msg": "Invoice uploaded and parsed",
        "invoice_id": updated_invoice.id,
        "parsed_fields": parsed_fields,
        "file_location": file_url,
    }


@router.post("/request_review")
async def request_review(
    invoice_id: int,
    current_user: users_models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    invoice = await invoices_crud.get_invoice_by_id_and_owner(
        db, invoice_id, current_user.id
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
        current_user.id,
        payload.reviewed,
        payload.corrected_fields,
    )
    if not invoice:
        raise HTTPException(
            status_code=404, detail={"ok": False, "msg": "Invoice not found"}
        )
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
            owner_id=current_user.id,
            invoice_type=invoice_type,
            search=search,
            from_date=from_date,
            to_date=to_date,
            ignore_pagination=True,
        )
        return {"ok": True, "invoices": invoices}

    parsed = parse_range(range_str)
    if isinstance(parsed, dict):  # error
        return parsed

    start, end = parsed
    limit = end - start + 1
    offset = start - 1

    invoices = await invoices_crud.list_invoices_by_owner(
        db,
        owner_id=current_user.id,
        invoice_type=invoice_type,
        limit=limit,
        offset=offset,
    )
    return {"ok": True, "invoices": invoices}


@router.get("/to_be_reviewed", response_model=invoices_schemas.InvoiceTBRListResponse)
async def to_be_reviewed(
    current_user: users_models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    invoices = await invoices_crud.list_invoices_to_review_by_owner(db, current_user.id)
    return {"ok": True, "invoices": invoices}


@router.post("/edit/{invoice_id}")
async def edit_invoice(
    invoice_id: int,
    payload: invoices_schemas.EditInvoiceFields,
    current_user: users_models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    invoice = await invoices_crud.edit_invoice(
        db, invoice_id, current_user.id, payload.corrected_fields
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
        db, invoice_id, current_user.id
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
        db, invoice_id, current_user.id
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
    invoice_id: int,
    current_user: users_models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    invoice = await invoices_crud.get_invoice_by_id_and_owner(
        db, invoice_id, current_user.id
    )
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    file_url = invoice.file_path

    did = await invoices_crud.delete_invoice(db, invoice_id, current_user.id)
    if not did:
        raise HTTPException(status_code=404, detail="Invoice not found or not deleted")

    if file_url:
        try:
            # Extract the object key from URL
            parsed = urlparse(file_url)
            key = parsed.path.lstrip("/")  # remove leading /
            s3.delete_object(Bucket=R2_BUCKET, Key=key)
        except Exception as e:
            print(f"Error deleting file from R2 {file_url}: {e}")

    return {"msg": "Invoice deleted", "invoice_id": invoice_id}


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

    parsed_fields = await loop.run_in_executor(None, process_with_qwen, content, ext)
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
        db, current_user.id, file_url, parsed_fields
    )

    return {
        "ok": True,
        "msg": f"{invoice_type.capitalize()} uploaded and parsed successfully (local mode)",
        "invoice_id": invoice.id,
        "parsed_fields": parsed_fields,
        "file_location": file_url,
    }


@router.post("/retry_extraction/{invoice_id}")
async def retry_extraction(
    invoice_id: int,
    current_user: users_models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    invoice = await invoices_crud.get_invoice_by_id_and_owner(
        db, invoice_id, current_user.id
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
    parsed_fields = await loop.run_in_executor(None, process_invoice, content, ext)

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
