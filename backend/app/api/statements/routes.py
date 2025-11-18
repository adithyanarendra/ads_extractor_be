from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
import asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.responses import StreamingResponse


from . import crud as statements_crud
from . import schemas as statement_schemas
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
    if statement_type not in statements_crud.ALLOWED_TYPES:
        return {
            "ok": False,
            "message": "Invalid statement type",
            "error": "Allowed types: bank, credit_card",
            "data": None,
        }

    file_bytes = await file.read()

    result = await statements_crud.create_statement(
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
        statements_crud.process_statement_background(
            statement_id=statement.id,
            file_bytes=file_bytes,
            file_ext=file.filename.split(".")[-1],
        )
    )

    return result


@router.get("/analytics")
async def get_analytics(
    db: AsyncSession = Depends(get_db), current_user=Depends(get_current_user)
):
    result = await statements_crud.get_statement_analytics(db, current_user)
    return result


@router.get("/")
async def get_statements(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    result = await statements_crud.list_statements(db, current_user)
    return result


@router.get("/items")
async def get_all_statement_items(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    result = await statements_crud.list_statement_items(db, current_user)
    return result


@router.get("/accounts")
async def get_accounts(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await statements_crud.list_accounts(db, current_user)


@router.get("/{statement_id}")
async def get_statement_detail(
    statement_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    result = await statements_crud.get_statement(db, statement_id, current_user)
    return result


@router.get("/download/{statement_id}")
async def download_statement_file(
    statement_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    stmt_result = await statements_crud.get_statement(db, statement_id, current_user)

    if not stmt_result["ok"]:
        return stmt_result

    stmt = stmt_result["data"]

    file_result = await statements_crud.download_file(stmt)
    if not file_result["ok"]:
        return file_result

    return StreamingResponse(file_result["data"], media_type="application/octet-stream")


@router.delete("/{statement_id}")
async def delete_statement_route(
    statement_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    result = await statements_crud.delete_statement(db, statement_id, current_user)
    return result


@router.delete("/items/{item_id}")
async def delete_statement_item_route(
    item_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    result = await statements_crud.delete_statement_item(db, item_id, current_user)
    return result


@router.delete("/account/{account_id}")
async def delete_account_route(
    account_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    from .crud import delete_account

    result = await delete_account(db, account_id, current_user)
    return result


@router.patch("/item/edit/{item_id}")
async def edit_statement_item(
    item_id: int,
    body: statement_schemas.StatementItemUniversalEditIn,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    result = await statements_crud.update_statement_item(
        db, item_id, current_user, body.updates
    )
    return result
