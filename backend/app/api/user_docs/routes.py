from fastapi import APIRouter, Depends, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
import asyncio
from ...core.database import get_db
from . import crud as user_docs_crud
from ..invoices.routes import get_current_user


router = APIRouter(prefix="/user_docs", tags=["user-docs"])


@router.get("/timeline")
async def get_docs_timeline(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await user_docs_crud.get_user_docs_for_timeline(db, current_user.id)


@router.post("/auto")
async def upload_doc_auto(
    file: UploadFile = File(...),
    expiry_date: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    file_bytes = await file.read()
    file.file.seek(0)

    result = await user_docs_crud.upload_user_doc(
        db=db,
        user_id=current_user.id,
        doc_type="auto",
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
        asyncio.create_task(
            user_docs_crud.process_doc_metadata(doc_data["id"], file_bytes, "auto")
        )
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
    return await user_docs_crud.list_user_docs(db, current_user.id)


@router.get("/details/{doc_id}")
async def get_doc_details(
    doc_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    result = await user_docs_crud.get_user_doc_details(db, current_user.id, doc_id)

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


@router.get("/{doc_id}")
async def get_doc(
    doc_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await user_docs_crud.get_user_doc(db, current_user.id, doc_id)


@router.delete("/{doc_id}")
async def remove_doc(
    doc_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    result = await user_docs_crud.delete_user_doc(db, current_user.id, doc_id)
    return result
