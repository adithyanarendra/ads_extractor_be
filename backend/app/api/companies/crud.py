from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import Optional, List
from .models import Company, CompanyUser
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


async def add_user_to_company(
    db: AsyncSession,
    company_id: int,
    user_id: int,
    added_by: Optional[int] = None,
    company_admin: bool = False,
) -> CompanyUser:
    q = await db.execute(
        select(CompanyUser).where(
            CompanyUser.company_id == company_id, CompanyUser.user_id == user_id
        )
    )
    existing = q.scalars().first()
    if existing:
        if existing.company_admin != company_admin:
            existing.company_admin = company_admin
            await db.commit()
            await db.refresh(existing)
        return existing

    assoc = CompanyUser(
        company_id=company_id,
        user_id=user_id,
        company_admin=company_admin,
        added_by=added_by,
    )
    db.add(assoc)
    await db.commit()
    await db.refresh(assoc)
    return assoc


async def remove_user_from_company(
    db: AsyncSession, company_id: int, user_id: int
) -> bool:
    q = await db.execute(
        select(CompanyUser).where(
            CompanyUser.company_id == company_id, CompanyUser.user_id == user_id
        )
    )
    assoc = q.scalars().first()
    if not assoc:
        return False
    await db.delete(assoc)
    await db.commit()
    return True


async def get_companies_for_user(db: AsyncSession, user_id: int) -> List[Company]:
    stmt = (
        select(Company)
        .join(CompanyUser, Company.id == CompanyUser.company_id)
        .where(CompanyUser.user_id == user_id)
    )
    result = await db.execute(stmt)
    return result.scalars().all()


async def get_company_users(db: AsyncSession, company_id: int):
    stmt = select(CompanyUser).where(CompanyUser.company_id == company_id)
    result = await db.execute(stmt)
    return result.scalars().all()


async def is_user_in_company(db: AsyncSession, user_id: int, company_id: int) -> bool:
    stmt = await db.execute(
        select(CompanyUser).where(
            CompanyUser.user_id == user_id, CompanyUser.company_id == company_id
        )
    )
    return stmt.scalars().first() is not None
