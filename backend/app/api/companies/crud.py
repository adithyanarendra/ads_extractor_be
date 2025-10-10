from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import Optional
from .models import Company
from datetime import datetime


async def create_company(db: AsyncSession, company_data: dict, current_user: str):
    now = datetime.utcnow()
    company = Company(
        **company_data,
        created_by=current_user,
        created_at=now,
        last_updated_by=current_user,
        last_updated_date=now,
    )
    db.add(company)
    await db.commit()
    await db.refresh(company)
    return company


async def update_company(
    db: AsyncSession, company_id: int, company_data: dict, current_user: str
):
    result = await db.execute(select(Company).where(Company.id == company_id))
    company = result.scalars().first()
    if not company:
        return None

    for key, value in company_data.items():
        if value is not None:
            setattr(company, key, value)

    company.last_updated_by = current_user
    company.last_updated_date = datetime.utcnow()

    db.add(company)
    await db.commit()
    await db.refresh(company)
    return company


async def get_company_by_id(db: AsyncSession, company_id: int) -> Optional[Company]:
    result = await db.execute(select(Company).where(Company.id == company_id))
    return result.scalars().first()


async def get_all_companies(db: AsyncSession):
    result = await db.execute(select(Company))
    return result.scalars().all()


async def delete_company(db: AsyncSession, company_id: int):
    result = await db.execute(select(Company).where(Company.id == company_id))
    company = result.scalars().first()
    if not company:
        return False
    await db.delete(company)
    await db.commit()
    return True
