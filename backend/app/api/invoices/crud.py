from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import delete, or_, and_, desc
from typing import Optional, Dict
from . import models as invoices_models
from datetime import datetime


async def create_invoice(
    db: AsyncSession, owner_id: int, file_path: str, fields: Dict[str, Optional[str]]
) -> invoices_models.Invoice:
    inv = invoices_models.Invoice(
        owner_id=owner_id,
        file_path=file_path,
        invoice_number=fields.get("invoice_number"),
        invoice_date=fields.get("invoice_date"),
        vendor_name=fields.get("vendor_name"),
        trn_vat_number=fields.get("trn_vat_number"),
        before_tax_amount=fields.get("before_tax_amount"),
        tax_amount=fields.get("tax_amount"),
        total=fields.get("total"),
        remarks=fields.get("remarks"),
        reviewed=False,
    )
    db.add(inv)
    await db.commit()
    await db.refresh(inv)
    return inv


async def get_invoice_by_id_and_owner(
    db: AsyncSession, invoice_id: int, owner_id: int
) -> Optional[invoices_models.Invoice]:
    stmt = (
        select(invoices_models.Invoice)
        .where(
            invoices_models.Invoice.id == invoice_id,
            invoices_models.Invoice.owner_id == owner_id,
        )
        .execution_options(populate_existing=False, autoflush=False, autocommit=False)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def list_invoices_by_owner(
    db: AsyncSession,
    owner_id: int,
    limit: int = 50,
    offset: int = 0,
    search: str | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    ignore_pagination: bool = False,
):
    stmt = select(invoices_models.Invoice).where(
        invoices_models.Invoice.owner_id == owner_id
    )

    if search:
        stmt = stmt.where(
            or_(
                invoices_models.Invoice.vendor_name.ilike(f"%{search}%"),
                invoices_models.Invoice.invoice_number.ilike(f"%{search}%"),
                invoices_models.Invoice.invoice_date.ilike(f"%{search}%"),
                invoices_models.Invoice.trn_vat_number.ilike(f"%{search}%"),
            )
        )

    if from_date and to_date:
        stmt = stmt.where(
            and_(
                invoices_models.Invoice.invoice_date >= from_date.strftime("%Y-%m-%d"),
                invoices_models.Invoice.invoice_date <= to_date.strftime("%Y-%m-%d"),
            )
        )
    elif from_date:
        stmt = stmt.where(
            invoices_models.Invoice.invoice_date >= from_date.strftime("%Y-%m-%d")
        )
    elif to_date:
        stmt = stmt.where(
            invoices_models.Invoice.invoice_date <= to_date.strftime("%Y-%m-%d")
        )

    stmt = stmt.order_by(desc(invoices_models.Invoice.created_at))

    if not ignore_pagination:
        stmt = stmt.offset(offset).limit(limit)

    result = await db.execute(stmt)
    return result.scalars().all()


async def list_invoices_to_review_by_owner(db: AsyncSession, owner_id: int):
    stmt = select(invoices_models.Invoice.id, invoices_models.Invoice.file_path).where(
        invoices_models.Invoice.owner_id == owner_id,
        invoices_models.Invoice.reviewed == False,
    )
    result = await db.execute(stmt)
    return [{"id": row.id, "file_path": row.file_path} for row in result.all()]


async def update_invoice_review(
    db: AsyncSession,
    invoice_id: int,
    owner_id: int,
    reviewed: bool,
    corrected_fields: Dict[str, Optional[str]] | None = None,
):
    invoice = await get_invoice_by_id_and_owner(db, invoice_id, owner_id)
    if not invoice:
        return None
    invoice.reviewed = reviewed
    if corrected_fields:
        allowed = {
            "invoice_number",
            "invoice_date",
            "vendor_name",
            "trn_vat_number",
            "before_tax_amount",
            "tax_amount",
            "total",
            "remarks",
        }
        for k, v in corrected_fields.items():
            if k in allowed:
                setattr(invoice, k, v)
    await db.commit()
    await db.refresh(invoice)
    return invoice


async def edit_invoice(
    db: AsyncSession,
    invoice_id: int,
    owner_id: int,
    corrected_fields: Dict[str, Optional[str]],
):
    invoice = await get_invoice_by_id_and_owner(db, invoice_id, owner_id)
    if not invoice:
        return None

    allowed = {
        "invoice_number",
        "invoice_date",
        "vendor_name",
        "trn_vat_number",
        "before_tax_amount",
        "tax_amount",
        "total",
        "remarks",
    }
    for k, v in corrected_fields.items():
        if k in allowed:
            setattr(invoice, k, v)

    await db.commit()
    await db.refresh(invoice)
    return invoice


async def delete_invoice(db: AsyncSession, invoice_id: int, owner_id: int) -> bool:
    # Use SQL delete for simplicity
    await db.execute(
        delete(invoices_models.Invoice).where(
            invoices_models.Invoice.id == invoice_id,
            invoices_models.Invoice.owner_id == owner_id,
        )
    )
    await db.commit()
    return True
