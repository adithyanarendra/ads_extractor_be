from fastapi import APIRouter, Depends, HTTPException, Header, Body
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...core import auth
from . import crud as companies_crud
from . import schemas as companies_schemas
from ..users import models as users_models
from ..users import crud as users_crud
from .models import CompanyUser

router = APIRouter(prefix="/companies", tags=["companies"])


async def get_current_user(current_user=Depends(auth.get_current_user)):
    return current_user


@router.post("/create")
async def create_company(
    payload: companies_schemas.CompanyCreate,
    current_user: users_models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    company = await companies_crud.create_company(
        db, payload.dict(), current_user.email
    )
    return {
        "ok": True,
        "company_details": companies_schemas.CompanyOut.from_orm(company),
    }


@router.put("/update/{company_id}")
async def update_company(
    company_id: int,
    payload: companies_schemas.CompanyUpdate,
    current_user: users_models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    company = await companies_crud.update_company(
        db, company_id, payload.dict(), current_user.email
    )
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    return {
        "ok": True,
        "company_details": companies_schemas.CompanyOut.from_orm(company),
    }


@router.get("/all")
async def get_all_companies(
    current_user: users_models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    companies = await companies_crud.get_all_companies(db)
    return {
        "ok": True,
        "companies": [companies_schemas.CompanyOut.from_orm(c) for c in companies],
    }


@router.get("/get_details/{company_id}")
async def get_company_details(
    company_id: int,
    current_user: users_models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    company = await companies_crud.get_company_by_id(db, company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    return {
        "ok": True,
        "company_details": companies_schemas.CompanyOut.from_orm(company),
    }


@router.delete("/delete/{company_id}")
async def delete_company(
    company_id: int,
    current_user: users_models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    success = await companies_crud.delete_company(db, company_id)
    if not success:
        raise HTTPException(status_code=404, detail="Company not found")
    return {"ok": True, "message": "Company deleted successfully"}


@router.get("/{company_id}/users")
async def get_company_users_route(
    company_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(CompanyUser, users_models.User)
        .join(users_models.User, CompanyUser.user_id == users_models.User.id)
        .where(CompanyUser.company_id == company_id)
    )

    result = await db.execute(stmt)
    rows = result.all()

    users = [
        {
            "id": r.User.id,
            "email": r.User.email,
            "company_admin": r.CompanyUser.company_admin,
        }
        for r in rows
    ]

    return {"ok": True, "users": users}


@router.post("/{company_id}/add_user")
async def add_user_to_company_route(
    company_id: int,
    payload: companies_schemas.AddUserPayload,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.is_super_admin:
        pass
    else:
        q = await db.execute(
            select(CompanyUser).where(
                CompanyUser.company_id == company_id,
                CompanyUser.user_id == current_user.id,
            )
        )
        assoc = q.scalar_one_or_none()
        if not assoc or not assoc.company_admin:
            if not (
                getattr(current_user, "jwt_is_accountant", False)
                and not current_user.is_admin
            ):
                return {"ok": False, "error": "Not authorized"}

    target = await users_crud.get_user_by_id(db, payload.user_id)
    if not target:
        return {"ok": False, "error": "User not found"}

    if getattr(current_user, "jwt_is_accountant", False) and not current_user.is_admin:
        if payload.company_admin and payload.user_id != current_user.id:
            return {
                "ok": False,
                "error": "Accountant cannot assign another user as company admin",
            }

        if payload.company_admin and payload.user_id == current_user.id:
            has_admin = await companies_crud.company_has_admin(db, company_id)
            if has_admin:
                return {
                    "ok": False,
                    "error": "Company already has admin; cannot self-assign",
                }

    new_assoc = await companies_crud.add_user_to_company(
        db,
        company_id,
        payload.user_id,
        added_by=current_user.id,
        company_admin=payload.company_admin,
    )

    return {"ok": True, "msg": "User added", "assoc_id": new_assoc.id}


@router.delete("/{company_id}/remove_user/{user_id}")
async def remove_user_from_company(
    company_id: int,
    user_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):

    if not current_user.is_super_admin:
        q = await db.execute(
            select(CompanyUser).where(
                CompanyUser.company_id == company_id,
                CompanyUser.user_id == current_user.id,
            )
        )
        assoc = q.scalar_one_or_none()
        if not assoc or not assoc.company_admin:
            raise HTTPException(status_code=403, detail="Not authorized")

    success = await companies_crud.remove_user_from_company(db, company_id, user_id)
    if not success:
        raise HTTPException(status_code=404, detail="Association not found")

    return {"ok": True, "msg": "User removed"}


@router.post("/convert_user_to_company")
async def convert_user_to_company(
    payload: companies_schemas.CompanyCreate,
    user_id: int | None = None,
    current_user: users_models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    target_user = None
    if user_id is None:
        target_user = current_user
    else:
        if not (
            current_user.is_admin or getattr(current_user, "jwt_is_super_admin", False)
        ):
            raise HTTPException(
                status_code=403, detail="Not authorized to convert another user"
            )
        target_user = await users_crud.get_user_by_id(db, user_id)
        if not target_user:
            raise HTTPException(status_code=404, detail="Target user not found")

    company = await companies_crud.create_company(
        db, payload.dict(), current_user.email
    )

    assoc = await companies_crud.add_user_to_company(
        db,
        company.id,
        target_user.id,
        added_by=current_user.id,
        company_admin=True,
    )

    return {
        "ok": True,
        "msg": "User converted to company successfully",
        "company": companies_schemas.CompanyOut.from_orm(company),
        "assoc_id": assoc.id,
    }
