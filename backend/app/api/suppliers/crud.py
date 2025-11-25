from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import update, func
from .models import Supplier, normalize_name
from typing import Optional, List
from ..invoices import models as invoice_models


async def get_supplier_by_normalized(db: AsyncSession, owner_id: int, norm: str):
    result = await db.execute(
        select(Supplier).where(
            Supplier.owner_id == owner_id,
            Supplier.normalized_name == norm,
            Supplier.merged_into_id.is_(None),
        )
    )
    return result.scalars().first()


async def create_or_get_supplier(
    db: AsyncSession, owner_id: int, company_id: int | None, name: str, trn: str | None
):
    norm = normalize_name(name)
    existing = await get_supplier_by_normalized(db, owner_id, norm)
    if existing:
        return existing

    supplier = Supplier(
        owner_id=owner_id,
        company_id=company_id,
        name=name,
        normalized_name=norm,
        trn_vat_number=trn,
    )
    db.add(supplier)
    await db.commit()
    await db.refresh(supplier)
    return supplier


async def list_suppliers(db: AsyncSession, owner_id: int, search: str | None = None):
    stmt = (
        select(Supplier, func.count(invoice_models.Invoice.id).label("invoice_count"))
        .outerjoin(
            invoice_models.Invoice, invoice_models.Invoice.supplier_id == Supplier.id
        )
        .where(
            Supplier.owner_id == owner_id,
            Supplier.is_active == True,
        )
        .group_by(Supplier.id)
        .order_by(Supplier.name.asc())
    )

    if search:
        stmt = stmt.where(Supplier.name.ilike(f"%{search}%"))

    result = await db.execute(stmt)
    rows = result.all()

    suppliers = []
    for supplier, invoice_count in rows:
        supplier.invoice_count = invoice_count
        suppliers.append(supplier)

    return suppliers


async def update_supplier(
    db: AsyncSession, supplier_id: int, owner_id: int, data: dict
):
    result = await db.execute(
        select(Supplier).where(
            Supplier.id == supplier_id, Supplier.owner_id == owner_id
        )
    )
    supplier = result.scalars().first()
    if not supplier:
        return None

    for k, v in data.items():
        setattr(supplier, k, v)

    if "name" in data:
        supplier.normalized_name = normalize_name(data["name"])

    await db.commit()
    await db.refresh(supplier)
    return supplier


async def merge_suppliers(
    db: AsyncSession, owner_id: int, source_ids: List[int], target_id: int
):
    await db.execute(
        update(Supplier)
        .where(Supplier.id.in_(source_ids), Supplier.owner_id == owner_id)
        .values(is_active=False, merged_into_id=target_id)
    )
    await db.commit()
    return True
