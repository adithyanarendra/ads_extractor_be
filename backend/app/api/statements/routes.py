from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
import asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.responses import StreamingResponse

from .crud import (
    create_statement,
    list_statements,
    list_statement_items,
    get_statement,
    download_file,
    ALLOWED_TYPES,
    delete_statement,
    delete_statement_item,
    process_statement_background,
)
from ...core.database import get_db
from ..invoices.routes import get_current_user

router = APIRouter(prefix="/statements", tags=["Statements"])


@router.post("/upload/{statement_type}")
async def upload_statement(
    statement_type: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if statement_type not in ALLOWED_TYPES:
        return {
            "ok": False,
            "message": "Invalid statement type",
            "error": "Allowed types: bank, credit_card",
            "data": None,
        }

    file_bytes = await file.read()

    result = await create_statement(
        db=db,
        user=current_user,
        statement_type=statement_type,
        file_bytes=file_bytes,
        filename=file.filename,
    )

    if not result["ok"]:
        return result

    statement = result["data"]

    asyncio.create_task(
        process_statement_background(
            statement_id=statement.id,
            file_bytes=file_bytes,
            file_ext=file.filename.split(".")[-1],
        )
    )

    return result


@router.get("/")
async def get_statements(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    result = await list_statements(db, current_user)
    return result


@router.get("/items")
async def get_all_statement_items(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    result = await list_statement_items(db, current_user)
    return result


@router.get("/{statement_id}")
async def get_statement_detail(
    statement_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    result = await get_statement(db, statement_id, current_user)
    return result


@router.get("/download/{statement_id}")
async def download_statement_file(
    statement_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    stmt_result = await get_statement(db, statement_id, current_user)

    if not stmt_result["ok"]:
        return stmt_result

    stmt = stmt_result["data"]

    file_result = await download_file(stmt)
    if not file_result["ok"]:
        return file_result

    return StreamingResponse(file_result["data"], media_type="application/octet-stream")


@router.delete("/{statement_id}")
async def delete_statement_route(
    statement_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    result = await delete_statement(db, statement_id, current_user)
    return result


@router.delete("/items/{item_id}")
async def delete_statement_item_route(
    item_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    result = await delete_statement_item(db, item_id, current_user)
    return result
