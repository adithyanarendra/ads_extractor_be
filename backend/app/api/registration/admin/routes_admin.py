from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.auth import get_current_user
from . import schemas_admin, crud_admin

router = APIRouter(prefix="/sales/registration", tags=["registration-admin"])


def ensure_sales_access(user):
    if not (user.jwt_is_super_admin or user.jwt_is_accountant or user.is_admin):
        raise HTTPException(status_code=403, detail="Not authorized")


@router.get("", response_model=list[schemas_admin.RegistrationAdminOut])
async def list_registrations(
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    ensure_sales_access(user)
    return await crud_admin.list_registrations_with_docs(db)


@router.post("/{registration_id}/approve")
async def approve_registration(
    registration_id: int,
    payload: schemas_admin.ApproveRegistrationRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    ensure_sales_access(user)
    try:
        return await crud_admin.approve_registration(
            db,
            registration_id,
            payload.name,
            payload.email,
            payload.password,
            user.id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{registration_id}/reject")
async def reject_registration(
    registration_id: int,
    payload: schemas_admin.RejectRegistrationRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    ensure_sales_access(user)

    if not payload.reason.strip():
        raise HTTPException(status_code=400, detail="Reject reason is required")

    await crud_admin.reject_registration(
        db,
        registration_id,
        payload.reason,
        user.id,
    )
    return {"ok": True}
