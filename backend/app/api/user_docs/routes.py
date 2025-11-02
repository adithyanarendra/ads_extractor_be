from fastapi import APIRouter, Depends, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
import asyncio

from ...core.database import get_db
from .crud import (
    upload_user_doc,
    list_user_docs,
    get_user_doc,
    delete_user_doc,
    process_doc_metadata,
    get_user_doc_details,
)
from ..invoices.routes import get_current_user


router = APIRouter(prefix="/user_docs", tags=["user-docs"])


@router.post("/{doc_type}")
async def upload_doc(
    doc_type: str,
    file: UploadFile = File(...),
    expiry_date: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    file_bytes = await file.read()
    file.file.seek(0)

    result = await upload_user_doc(
        db=db,
        user_id=current_user.id,
        doc_type=doc_type,
        file_bytes=file_bytes,
        file=file,
        expiry_date=expiry_date,
    )

    if not result.get("ok"):
        return {
            "ok": False,
            "message": result.get("message", "Upload failed"),
            "error": result.get("error", "Unknown error"),
        }

    doc_data = result.get("data")

    try:
        asyncio.create_task(process_doc_metadata(doc_data["id"], file_bytes, doc_type))
    except Exception as e:
        print("Meta extraction dispatch error:", e)

    return {
        "ok": True,
        "message": result.get("message", "Upload success"),
        "data": doc_data,
    }


@router.get("/")
async def get_all_docs(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await list_user_docs(db, current_user.id)


@router.get("/details/{doc_type}")
async def get_doc_details(
    doc_type: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):

    result = await get_user_doc_details(db, current_user.id, doc_type)

    if not result.get("ok"):
        return {
            "ok": False,
            "message": result.get("message", "Failed to fetch document details"),
            "error": result.get("error", "Unknown error"),
            "data": None,
        }

    return {
        "ok": True,
        "message": result.get("message", "Document details fetched successfully"),
        "data": result.get("data"),
    }


@router.get("/{doc_type}")
async def get_doc(
    doc_type: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await get_user_doc(db, current_user.id, doc_type)


@router.delete("/{doc_type}")
async def remove_doc(
    doc_type: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    await delete_user_doc(db, current_user.id, doc_type)
    return {"ok": True, "message": f"{doc_type} deleted"}
