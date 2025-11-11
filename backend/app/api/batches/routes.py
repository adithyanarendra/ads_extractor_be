from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from ..users import models as users_models
from ..invoices.routes import get_current_user
from app.core.database import get_db
from .schemas import BatchCreate, AddInvoicesPayload
from . import crud

router = APIRouter(prefix="/batches", tags=["Batches"])


@router.get("/all")
async def get_all_batches(
    db: AsyncSession = Depends(get_db),
    current_user: users_models.User = Depends(get_current_user),
):
    res = await crud.list_batches(db, owner_id=current_user.id)
    return res


@router.get("/{batch_id}")
async def get_batch_invoice_ids(
    batch_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: users_models.User = Depends(get_current_user),
):
    res = await crud.get_invoice_ids_for_batch(db, batch_id, owner_id=current_user.id)
    if not res.get("ok"):
        raise HTTPException(status_code=404, detail=res.get("message"))
    return res


@router.post("/add")
async def add_batch(
    payload: BatchCreate,
    db: AsyncSession = Depends(get_db),
    current_user: users_models.User = Depends(get_current_user),
):
    res = await crud.create_batch(
        db,
        payload.name,
        owner_id=current_user.id,
        invoice_ids=getattr(payload, "invoice_ids", None),
    )
    return res


@router.post("/add/{batch_id}")
async def add_invoices(
    batch_id: int,
    payload: AddInvoicesPayload,
    db: AsyncSession = Depends(get_db),
    current_user: users_models.User = Depends(get_current_user),
):
    res = await crud.add_invoices_to_batch(
        db, batch_id, payload.invoice_ids, owner_id=current_user.id
    )
    return res


@router.post("/lock/{batch_id}")
async def toggle_lock(
    batch_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: users_models.User = Depends(get_current_user),
):
    res = await crud.toggle_lock(db, batch_id, owner_id=current_user.id)
    return res


@router.delete("/batch/{batch_id}")
async def delete_batch(
    batch_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: users_models.User = Depends(get_current_user),
):
    res = await crud.delete_batch_if_unlocked(db, batch_id, owner_id=current_user.id)
    return res


@router.get("/download-zip/{batch_id}")
async def download_batch_zip(
    batch_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: users_models.User = Depends(get_current_user),
):
    try:
        zip_buffer, batch_name = await crud.generate_batch_zip_with_csv(
            db, batch_id, current_user.id
        )
        zip_size = zip_buffer.getbuffer().nbytes
        return StreamingResponse(
            zip_buffer,
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{batch_name}.zip"',
                "Content-Length": str(zip_size),
            },
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
