import os
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
from ...utils.r2 import upload_to_r2_bytes, get_file_from_r2
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
    if doc_type not in ALLOWED_DOC_TYPES:
        return {
            "ok": False,
            "error": "Invalid document type",
            "message": "Upload failed",
        }

    user = await get_user_by_id(db, user_id)
    if not user:
        return {"ok": False, "error": "User not found", "message": "Upload failed"}

    # detect extension
    ext = os.path.splitext(file.filename)[1].lower()

    if not ext:
        if file.content_type == "application/pdf":
            ext = ".pdf"
        elif file.content_type in ["image/jpeg", "image/jpg"]:
            ext = ".jpg"
        elif file.content_type == "image/png":
            ext = ".png"
        else:
            ext = mimetypes.guess_extension(file.content_type) or ".pdf"

    filename_with_ext = f"{doc_type}{ext}"
    r2_key = f"{user_id}/{filename_with_ext}"

    file_url = upload_to_r2_bytes(file_bytes, r2_key)

    await db.execute(
        delete(UserDocs).where(
            UserDocs.user_id == user_id, UserDocs.file_name.like(f"{doc_type}%")
        )
    )
    await db.commit()
    existing = await db.execute(
        select(UserDocs).where(
            UserDocs.user_id == user_id, UserDocs.file_name == doc_type
        )
    )
    existing_doc = existing.scalar_one_or_none()

    if existing_doc:
        existing_doc.file_name = doc_type
        existing_doc.file_url = file_url
        existing_doc.expiry_date = expiry_date
        await db.commit()
        await db.refresh(existing_doc)
        return {
            "ok": True,
            "data": {
                "id": existing_doc.id,
                "file_url": file_url,
                "expiry_date": expiry_date,
            },
        }

    new_doc = UserDocs(
        user_id=user_id,
        file_name=doc_type,
        file_url=file_url,
        expiry_date=expiry_date,
    )
    db.add(new_doc)
    await db.commit()
    await db.refresh(new_doc)

    return {
        "ok": True,
        "data": {"id": new_doc.id, "file_url": file_url, "expiry_date": expiry_date},
    }


async def list_user_docs(db: AsyncSession, user_id: int) -> List[UserDocs]:
    """Return all uploaded documents for the logged-in user."""
    try:
        result = await db.execute(select(UserDocs).where(UserDocs.user_id == user_id))
        docs = result.scalars().all()
        data = [
            {
                "file_name": d.file_name,
                "file_url": d.file_url,
                "expiry_date": d.expiry_date,
            }
            for d in docs
        ]
        return {"ok": True, "message": "Documents retrieved successfully", "data": data}
    except Exception as e:
        return {"ok": False, "error": str(e), "message": "Failed to fetch documents"}


async def get_user_doc(db: AsyncSession, user_id: int, doc_type: str):
    if doc_type not in ALLOWED_DOC_TYPES:
        raise HTTPException(status_code=400, detail="Invalid document type")

    result = await db.execute(
        select(UserDocs)
        .where(UserDocs.user_id == user_id, UserDocs.file_name.like(f"{doc_type}%"))
        .order_by(UserDocs.updated_at.desc())
        .limit(1)
    )
    doc = result.scalar_one_or_none()

    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    filename = doc.file_url.split("r2.dev/")[-1]
    file_stream = get_file_from_r2(filename)

    if not file_stream:
        raise HTTPException(status_code=404, detail="File missing from R2")

    mime_type, _ = mimetypes.guess_type(filename)

    if not mime_type:
        mime_type = "application/octet-stream"

    headers = {"Content-Disposition": f'inline; filename="{filename.split("/")[-1]}"'}

    return StreamingResponse(file_stream, media_type=mime_type, headers=headers)


async def delete_user_doc(db: AsyncSession, user_id: int, doc_type: str):
    """Delete a specific document for the logged-in user."""
    if doc_type not in ALLOWED_DOC_TYPES:
        return {
            "ok": False,
            "error": "Invalid document type",
            "message": "Delete failed",
        }

    try:
        await db.execute(
            delete(UserDocs).where(
                UserDocs.user_id == user_id, UserDocs.file_name == doc_type
            )
        )
        await db.commit()
        return {"ok": True, "message": f"{doc_type} deleted successfully"}
    except Exception as e:
        await db.rollback()
        return {"ok": False, "error": str(e), "message": "Delete failed"}


async def process_documents_info(db: AsyncSession, doc: UserDocs):

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


async def process_doc_metadata(doc_id, file_bytes, doc_type: str):
    if not file_bytes or len(file_bytes) < 100:
        print(f"[WARN] Empty or invalid file_bytes for doc {doc_id}")
        return

    async with SessionLocal() as db:
        await extract_document_meta(
            db=db, doc_id=doc_id, file_bytes=file_bytes, doc_type=doc_type
        )


async def get_user_doc_details(db: AsyncSession, user_id: int, doc_type: str):
    """Return metadata details for a specific uploaded document (no file streaming)."""
    if doc_type not in ALLOWED_DOC_TYPES:
        return {
            "ok": False,
            "error": "Invalid document type",
            "message": "Invalid request",
        }

    result = await db.execute(
        select(UserDocs).where(
            UserDocs.user_id == user_id, UserDocs.file_name == doc_type
        )
    )
    doc = result.scalar_one_or_none()

    if not doc:
        return {
            "ok": False,
            "error": "Document not found",
            "message": "No document found",
        }

    Schema = DOC_SCHEMA_MAP.get(doc_type, BaseDocSchema)

    return {
        "ok": True,
        "message": "Document metadata retrieved successfully",
        "data": Schema.from_orm(doc).dict(),
    }
