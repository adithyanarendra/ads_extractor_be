from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from ...core.database import get_db
from ...core import auth
from ..users import crud as users_crud
from . import crud, schemas

router = APIRouter(prefix="/suppliers", tags=["suppliers"])


async def get_current_user(current_user=Depends(auth.get_current_user)):
    return current_user


@router.get("/", response_model=schemas.SupplierListResponse)
async def list_suppliers(
    search: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if not current_user:
        return {"ok": False, "error": "Unauthorized"}

    suppliers = await crud.list_suppliers(db, current_user.effective_user_id, search)

    return {
        "ok": True,
        "message": "Suppliers fetched",
        "data": suppliers,
        "total_count": len(suppliers),
    }


@router.post("/", response_model=schemas.ApiResponse)
async def create_supplier(
    payload: schemas.SupplierCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if not current_user:
        return {"ok": False, "error": "Unauthorized"}

    supplier = await crud.create_or_get_supplier(
        db,
        current_user.effective_user_id,
        getattr(current_user, "company_id", None),
        payload.name,
        payload.trn_vat_number,
    )

    supplier = await crud.update_supplier(
        db,
        supplier.id,
        current_user.effective_user_id,
        payload.dict(exclude_unset=True),
    )

    return {
        "ok": True,
        "message": "Supplier created",
        "data": supplier,
    }


@router.put("/{supplier_id}", response_model=schemas.ApiResponse)
async def update_supplier(
    supplier_id: int,
    payload: schemas.SupplierUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if not current_user:
        return {"ok": False, "error": "Unauthorized"}

    updated_supplier = await crud.update_supplier(
        db,
        supplier_id,
        current_user.effective_user_id,
        payload.dict(exclude_unset=True),
    )

    if not updated_supplier:
        return {"ok": False, "error": "Supplier not found"}

    supplier_out = schemas.SupplierOut.model_validate(
        updated_supplier, from_attributes=True
    )

    return {
        "ok": True,
        "message": "Supplier updated",
        "data": supplier_out,
    }


@router.post("/merge", response_model=schemas.ApiResponse)
async def merge_suppliers(
    payload: schemas.MergeRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if not current_user:
        return {"ok": False, "error": "Unauthorized"}

    await crud.merge_suppliers(
        db,
        current_user.effective_user_id,
        payload.source_supplier_ids,
        payload.target_supplier_id,
    )

    return {
        "ok": True,
        "message": "Suppliers merged",
        "data": None,
    }
