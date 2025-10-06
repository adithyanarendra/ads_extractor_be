import shutil
import os
from uuid import uuid4
import mimetypes
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from urllib.parse import urlparse


from app.core import auth
from ..users import schemas as users_schemas
from ..users import models as users_models
from ..users import crud as users_crud
from . import schemas as invoices_schemas
from . import crud as invoices_crud
from ...core.database import get_db
from ...utils.ocr_parser import process_invoice
from ...utils.r2 import upload_to_r2, get_file_from_r2, s3, R2_BUCKET

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


@router.post("/extract")
async def extract_invoice(
    file: UploadFile = File(...),
    current_user: users_models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Save file with a unique filename to avoid collisions
    ext = os.path.splitext(file.filename)[1]
    safe_name = f"{uuid4().hex}{ext}"
    local_path = os.path.join(UPLOAD_DIR, safe_name)

    try:
        with open(local_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        parsed_fields = process_invoice(local_path)

        with open(local_path, "rb") as f:
            file_url = upload_to_r2(f, safe_name)

    finally:
        if os.path.exists(local_path):
            try:
                os.remove(local_path)
            except Exception as e:
                print(f"Failed to delete temp file {local_path}: {e}")

    invoice = await invoices_crud.create_invoice(
        db, current_user.id, file_url, parsed_fields
    )

    return {
        "msg": "Invoice uploaded and parsed",
        "invoice_id": invoice.id,
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


@router.get("/all", response_model=invoices_schemas.InvoiceListResponse)
async def get_all_invoices(
    current_user: users_models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    invoices = await invoices_crud.list_invoices_by_owner(db, current_user.id)
    return {"ok": True, "invoices": invoices}


@router.get("/to_be_reviewed", response_model=list[invoices_schemas.InvoiceOut])
async def to_be_reviewed(
    current_user: users_models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    invoices = await invoices_crud.list_invoices_to_review_by_owner(db, current_user.id)
    return invoices


@router.get("/{invoice_id}", response_model=invoices_schemas.InvoiceOut)
async def get_invoice(
    invoice_id: int,
    current_user: users_models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    invoice = await invoices_crud.get_invoice_by_id_and_owner(
        db, invoice_id, current_user.id
    )
    if not invoice or invoice.reviewed:
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

    # Extract filename/key from the stored URL
    filename = invoice.file_path.split("/")[-1]
    file_obj = get_file_from_r2(filename)

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
