from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import delete
from typing import Optional, Dict
from . import models
from .auth import get_password_hash

async def get_user_by_email(db: AsyncSession, email: str) -> Optional[models.User]:
    result = await db.execute(select(models.User).where(models.User.email == email))
    return result.scalar_one_or_none()

async def create_user(db: AsyncSession, email: str, password: str) -> models.User:
    hashed = get_password_hash(password)
    user = models.User(email=email, hashed_password=hashed)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user

async def authenticate_user(db: AsyncSession, email: str, password: str):
    user = await get_user_by_email(db, email)
    if not user:
        return None
    from .auth import verify_password
    if not verify_password(password, user.hashed_password):
        return None
    return user

async def create_invoice(db: AsyncSession, owner_id: int, file_path: str, fields: Dict[str, Optional[str]]) -> models.Invoice:
    inv = models.Invoice(
        owner_id=owner_id,
        file_path=file_path,
        invoice_number=fields.get("invoice_number"),
        invoice_date=fields.get("invoice_date"),
        vendor_name=fields.get("vendor_name"),
        trn_vat_number=fields.get("trn_vat_number"),
        before_tax_amount=fields.get("before_tax_amount"),
        tax_amount=fields.get("tax_amount"),
        total=fields.get("total"),
        reviewed=False
    )
    db.add(inv)
    await db.commit()
    await db.refresh(inv)
    return inv

async def get_invoice_by_id_and_owner(db: AsyncSession, invoice_id: int, owner_id: int) -> Optional[models.Invoice]:
    result = await db.execute(
        select(models.Invoice).where(models.Invoice.id == invoice_id, models.Invoice.owner_id == owner_id)
    )
    return result.scalar_one_or_none()

async def list_invoices_by_owner(db: AsyncSession, owner_id: int):
    result = await db.execute(select(models.Invoice).where(models.Invoice.owner_id == owner_id))
    return result.scalars().all()

async def list_invoices_to_review_by_owner(db: AsyncSession, owner_id: int):
    result = await db.execute(select(models.Invoice).where(models.Invoice.owner_id == owner_id, models.Invoice.reviewed == False))
    return result.scalars().all()

async def update_invoice_review(db: AsyncSession, invoice_id: int, owner_id: int, reviewed: bool, corrected_fields: Dict[str, Optional[str]] | None = None):
    invoice = await get_invoice_by_id_and_owner(db, invoice_id, owner_id)
    if not invoice:
        return None
    invoice.reviewed = reviewed
    if corrected_fields:
        # Only update the allowed fields if present
        allowed = {"invoice_number", "invoice_date", "vendor_name", "trn_vat_number", "before_tax_amount", "tax_amount", "total"}
        for k, v in corrected_fields.items():
            if k in allowed:
                setattr(invoice, k, v)
    await db.commit()
    await db.refresh(invoice)
    return invoice

async def delete_invoice(db: AsyncSession, invoice_id: int, owner_id: int) -> bool:
    # Use SQL delete for simplicity
    await db.execute(delete(models.Invoice).where(models.Invoice.id == invoice_id, models.Invoice.owner_id == owner_id))
    await db.commit()
    return True
