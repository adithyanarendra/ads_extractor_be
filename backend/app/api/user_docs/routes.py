from fastapi import APIRouter, Depends, UploadFile, File, Body
from sqlalchemy.ext.asyncio import AsyncSession
import asyncio
from ...core.database import get_db
from . import crud as user_docs_crud
from . import schemas as user_docs_schemas
from ..invoices.routes import get_current_user


router = APIRouter(prefix="/user_docs", tags=["user-docs"])


@router.get("/processing_count")
async def get_processing_count_route(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    count = await user_docs_crud.get_processing_count(
        db, current_user.effective_user_id
    )

    return {"ok": True, "count": count}


@router.post("/sales_logo")
async def upload_sales_logo_route(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await user_docs_crud.upload_sales_logo(
        db, current_user.effective_user_id, file
    )


@router.get("/sales_logo")
async def get_sales_logo_route(
    db: AsyncSession = Depends(get_db), current_user=Depends(get_current_user)
):
    doc = await user_docs_crud.get_sales_logo(db, current_user.effective_user_id)
    return {"ok": True, "data": doc.file_url if doc else None}


@router.get("/timeline")
async def get_docs_timeline(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await user_docs_crud.get_user_docs_for_timeline(
        db, current_user.effective_user_id
    )


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
        user_id=current_user.effective_user_id,
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
    return await user_docs_crud.list_user_docs(db, current_user.effective_user_id)


@router.patch("/{doc_id}")
async def patch_user_doc(
    doc_id: int,
    payload: user_docs_schemas.UpdateUserDocSchema = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    data = payload.dict(exclude_unset=True)
    res = await user_docs_crud.update_user_doc(
        db, current_user.effective_user_id, doc_id, data
    )
    if not res.get("ok"):
        return {
            "ok": False,
            "message": res.get("message", "Update failed"),
            "error": res.get("error"),
        }
    return {
        "ok": True,
        "message": res.get("message", "Document updated"),
        "data": res.get("data"),
    }


@router.get("/details/{doc_id}")
async def get_doc_details(
    doc_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    result = await user_docs_crud.get_user_doc_details(
        db, current_user.effective_user_id, doc_id
    )

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
    return await user_docs_crud.get_user_doc(db, current_user.effective_user_id, doc_id)


@router.delete("/{doc_id}")
async def remove_doc(
    doc_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    result = await user_docs_crud.delete_user_doc(
        db, current_user.effective_user_id, doc_id
    )
    return result
