from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from ...core.database import get_db
from ...core import auth
from . import crud as companies_crud
from . import schemas as companies_schemas
from ..users import models as users_models
from ..users import crud as users_crud


router = APIRouter(prefix="/companies", tags=["companies"])


async def get_current_user(
    token: str = Depends(auth.oauth2_scheme),
    db: AsyncSession = Depends(get_db),
):
    decoded = auth.decode_token(token)
    if not decoded.get("ok"):
        raise HTTPException(
            status_code=401,
            detail=decoded.get("error", "Invalid or expired token"),
        )

    email = decoded.get("email")
    if not email:
        raise HTTPException(status_code=401, detail="Token missing email")

    user = await users_crud.get_user_by_email(db, email)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    return user


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
