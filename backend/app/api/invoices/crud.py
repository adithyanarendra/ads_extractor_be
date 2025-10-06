from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import delete
from typing import Optional, Dict
from . import models as invoices_models


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
        reviewed=False,
    )
    db.add(inv)
    await db.commit()
    await db.refresh(inv)
    return inv


async def get_invoice_by_id_and_owner(
    db: AsyncSession, invoice_id: int, owner_id: int
) -> Optional[invoices_models.Invoice]:
    result = await db.execute(
        select(invoices_models.Invoice).where(
            invoices_models.Invoice.id == invoice_id,
            invoices_models.Invoice.owner_id == owner_id,
        )
    )
    return result.scalar_one_or_none()


async def list_invoices_by_owner(db: AsyncSession, owner_id: int):
    result = await db.execute(
        select(invoices_models.Invoice).where(
            invoices_models.Invoice.owner_id == owner_id
        )
    )
    return result.scalars().all()


async def list_invoices_to_review_by_owner(db: AsyncSession, owner_id: int):
    result = await db.execute(
        select(invoices_models.Invoice).where(
            invoices_models.Invoice.owner_id == owner_id,
            invoices_models.Invoice.reviewed == False,
        )
    )
    return result.scalars().all()


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
        # Only update the allowed fields if present
        allowed = {
            "invoice_number",
            "invoice_date",
            "vendor_name",
            "trn_vat_number",
            "before_tax_amount",
            "tax_amount",
            "total",
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
