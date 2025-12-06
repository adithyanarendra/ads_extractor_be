import os
from re import findall
import asyncio
from calendar import month_abbr
from datetime import datetime, timezone
from fastapi import UploadFile, HTTPException, status
from fastapi.responses import StreamingResponse
from fastapi.concurrency import run_in_threadpool
import mimetypes
from sqlalchemy.future import select
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List

from ...core.database import SessionLocal
from .models import UserDocs
from ..users.crud import get_user_by_id
from ..batches import crud as batches_crud
from ...utils.r2 import upload_to_r2_bytes, get_file_from_r2, delete_from_r2
from ...utils.user_doc_parser import extract_document_meta

from ...utils.doc_prompts import ALLOWED_DOC_TYPES

from .schemas import DOC_SCHEMA_MAP, BaseDocSchema


async def upload_user_doc(
    db: AsyncSession,
    user_id: int,
    doc_type: str,
    file_bytes: bytes,
    file: UploadFile,
    expiry_date: Optional[str] = None,
):
    user = await get_user_by_id(db, user_id)
    if not user:
        return {"ok": False, "error": "User not found", "message": "Upload failed"}

    ext = os.path.splitext(file.filename)[1].lower()

    if not ext:
        if file.content_type == "application/pdf":
            ext = ".pdf"
        elif file.content_type in ["image/jpeg", "image/jpg"]:
            ext = ".jpg"
        elif file.content_type == "image/png":
            ext = ".png"
        else:
            import mimetypes

            ext = mimetypes.guess_extension(file.content_type) or ".pdf"

    timestamp = int(datetime.now(timezone.utc).timestamp())
    filename_with_ext = f"{doc_type}_{timestamp}{ext}"
    r2_key = f"{user_id}/{filename_with_ext}"

    file_url = upload_to_r2_bytes(file_bytes, r2_key)

    original_name = os.path.splitext(file.filename)[0] or filename_with_ext

    new_doc = UserDocs(
        user_id=user_id,
        file_name=original_name,
        file_url=file_url,
        expiry_date=expiry_date,
        doc_type=None,
    )
    db.add(new_doc)
    await db.commit()
    await db.refresh(new_doc)

    return {
        "ok": True,
        "data": {
            "id": new_doc.id,
            "file_url": new_doc.file_url,
            "expiry_date": expiry_date,
        },
    }


async def list_user_docs(db: AsyncSession, user_id: int) -> List[UserDocs]:
    try:
        result = await db.execute(
            select(UserDocs).where(
                UserDocs.user_id == user_id, UserDocs.doc_type != "sales_invoice_logo"
            )
        )
        docs = result.scalars().all()
        data = [
            {
                "id": d.id,
                "file_name": d.file_name,
                "doc_type": d.doc_type,
                "file_url": d.file_url,
                "expiry_date": d.expiry_date,
                "uploaded_at": d.uploaded_at,
            }
            for d in docs
        ]
        return {"ok": True, "message": "Documents retrieved successfully", "data": data}
    except Exception as e:
        return {"ok": False, "error": str(e), "message": "Failed to fetch documents"}


async def get_user_doc(db: AsyncSession, user_id: int, doc_id: int):
    result = await db.execute(
        select(UserDocs).where(UserDocs.user_id == user_id, UserDocs.id == doc_id)
    )
    doc = result.scalar_one_or_none()

    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Extract key from stored URL
    if "r2.dev/" in doc.file_url:
        filename = doc.file_url.split("r2.dev/")[-1]
    else:
        # if you're storing plain keys, adjust accordingly
        filename = doc.file_url

    file_stream = get_file_from_r2(filename)

    if not file_stream:
        raise HTTPException(status_code=404, detail="File missing from R2")

    import mimetypes

    mime_type, _ = mimetypes.guess_type(filename)
    if not mime_type:
        mime_type = "application/octet-stream"

    headers = {
        "Content-Disposition": f'inline; filename="{os.path.basename(filename)}"'
    }

    return StreamingResponse(file_stream, media_type=mime_type, headers=headers)


async def delete_user_doc(db: AsyncSession, user_id: int, doc_id: int):
    try:
        result = await db.execute(
            select(UserDocs).where(UserDocs.user_id == user_id, UserDocs.id == doc_id)
        )
        doc = result.scalar_one_or_none()

        if not doc:
            return {
                "ok": False,
                "error": "Document not found",
                "message": "Delete failed",
            }

        await db.execute(
            delete(UserDocs).where(
                UserDocs.user_id == user_id,
                UserDocs.id == doc_id,
            )
        )
        await db.commit()
        return {"ok": True, "message": f"Document {doc_id} deleted successfully"}
    except Exception as e:
        await db.rollback()
        return {"ok": False, "error": str(e), "message": "Delete failed"}


async def process_documents_info(db: AsyncSession, doc: UserDocs):
    if doc.doc_type == "sales_invoice_logo":
        return
    file_key = doc.file_url.split("r2.dev/")[-1]
    file_bytes = get_file_from_r2(file_key).read()

    ext = "." + file_key.split(".")[-1]

    data = await run_in_threadpool(extract_document_meta, file_bytes, ext)
    if not data:
        return

    doc.expiry_date = data.get("expiry_date") or doc.expiry_date
    doc.filing_date = data.get("filing_date")
    doc.batch_start_date = data.get("batch_start_date")
    doc.company_address = data.get("company_address")

    await db.commit()
    await db.refresh(doc)


async def process_doc_metadata(doc_id: int, file_bytes: bytes, doc_type: str):
    if doc_type == "sales_invoice_logo":
        return
    if not file_bytes or len(file_bytes) < 100:
        print(f"[WARN] Empty or invalid file_bytes for doc {doc_id}")
        return

    async with SessionLocal() as db:
        await extract_document_meta(
            db=db, doc_id=doc_id, file_bytes=file_bytes, doc_type=doc_type
        )

        result = await db.execute(select(UserDocs).where(UserDocs.id == doc_id))
        doc = result.scalar_one_or_none()
        if not doc:
            return

        # If VAT, create batches
        if doc.doc_type == "vat_certificate":
            await _autocreate_vat_batches_for_doc(db, doc)


async def get_user_doc_details(db: AsyncSession, user_id: int, doc_id: int):
    result = await db.execute(
        select(UserDocs).where(UserDocs.user_id == user_id, UserDocs.id == doc_id)
    )
    doc = result.scalar_one_or_none()

    if not doc:
        return {
            "ok": False,
            "error": "Document not found",
            "message": "No document found",
        }

    doc_type = doc.doc_type
    Schema = DOC_SCHEMA_MAP.get(doc_type, BaseDocSchema)

    return {
        "ok": True,
        "message": "Document metadata retrieved successfully",
        "data": Schema.from_orm(doc).dict(),
    }


async def _autocreate_vat_batches_for_doc(db: AsyncSession, doc: UserDocs):
    """
    Create batches for non-null VAT periods using the exact extracted string as the batch name.
    - Creates only if the value exists (skip nulls)
    - No duplicates: relies on batches.crud.create_batch duplicate check
    - Do NOT lock automatically
    """
    owner_id = doc.user_id

    period_names = [
        doc.vat_batch_one,
        doc.vat_batch_two,
        doc.vat_batch_three,
        doc.vat_batch_four,
    ]

    for name in period_names:
        if not name:
            continue
        years = findall(r"\b(20\d{2})\b", name)
        batch_year = int(years[0]) if years else None

        res = await batches_crud.create_batch(
            db, name=name, owner_id=owner_id, invoice_ids=None, batch_year=batch_year
        )

        if res.get("ok"):
            parent_id = res["data"]["id"]
            asyncio.create_task(_autocreate_child_batches(owner_id, name, parent_id))


async def _autocreate_child_batches(
    owner_id: int, parent_name: str, parent_id: Optional[int] = None
):
    async with SessionLocal() as db:
        parsed = batches_crud.parse_batch_range(parent_name)
        if not parsed:
            print(f"[child-batches] Skipping invalid range: {parent_name}")
            return

        start_month, end_month, start_year, end_year = parsed

        current_year = start_year
        month = start_month

        while True:
            month_name = month_abbr[month]
            child_name = f"{month_name} {current_year}"

            try:
                await batches_crud.create_batch(
                    db,
                    name=child_name,
                    owner_id=owner_id,
                    invoice_ids=None,
                    batch_year=current_year,
                    parent_id=parent_id,
                )
                print(
                    f"[child-batches] ✅ Created child batch: {child_name} (parent={parent_id})"
                )
            except Exception as e:
                print(f"[child-batches] ⚠️ Skipped child {child_name}: {e}")

            if current_year == end_year and month == end_month:
                break

            month += 1
            if month > 12:
                month = 1
                current_year += 1


async def get_user_docs_for_timeline(db: AsyncSession, user_id: int):
    result = await db.execute(
        select(UserDocs).where(
            UserDocs.user_id == user_id, UserDocs.doc_type != "sales_invoice_logo"
        )
    )
    docs = result.scalars().all()

    timeline = []
    now = datetime.now(timezone.utc)

    for d in docs:
        expiry = (
            d.expiry_date
            or d.tl_expiry_date
            or d.passport_expiry_date
            or d.emirates_id_expiry_date
        )

        if expiry:
            days_left = (expiry - now).days
        else:
            days_left = None

        timeline.append(
            {
                "id": d.id,
                "file_name": d.file_name,
                "doc_type": d.doc_type,
                "expiry_date": expiry,
                "days_left": days_left,
            }
        )

    timeline_sorted = sorted(
        timeline,
        key=lambda x: (
            x["days_left"] is None,
            x["days_left"] if x["days_left"] is not None else 999999,
        ),
    )

    return {
        "ok": True,
        "message": "Timeline sorted successfully",
        "data": timeline_sorted,
    }


async def get_sales_logo(db: AsyncSession, user_id: int):
    res = await db.execute(
        select(UserDocs).where(
            UserDocs.user_id == user_id, UserDocs.doc_type == "sales_invoice_logo"
        )
    )
    return res.scalar_one_or_none()


async def upload_sales_logo(db: AsyncSession, user_id: int, file: UploadFile):
    allowed = ["image/png", "image/jpeg", "image/jpg", "image/webp"]
    if file.content_type not in allowed:
        return {"ok": False, "message": "Invalid image type"}

    file_bytes = await file.read()

    existing = await get_sales_logo(db, user_id)
    if existing:
        try:
            key = existing.file_url.split("r2.dev/")[-1]
            delete_from_r2(key)
        except:
            pass
        await db.delete(existing)
        await db.commit()

    ext = ".png"
    r2_key = f"{user_id}/sales-invoice-logo-{user_id}{ext}"

    url = upload_to_r2_bytes(file_bytes, r2_key)

    new_doc = UserDocs(
        user_id=user_id,
        doc_type="sales_invoice_logo",
        file_name=f"sales-invoice-logo-{user_id}",
        file_url=url,
        expiry_date=None,
    )
    db.add(new_doc)
    await db.commit()
    await db.refresh(new_doc)

    return {"ok": True, "data": url}
