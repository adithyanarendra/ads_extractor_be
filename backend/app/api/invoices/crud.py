from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import update, delete, or_, and_, desc, func, Float
import re
from typing import Optional, Dict
from . import models as invoices_models
from datetime import datetime
import asyncio
from ...utils.ocr_parser import process_invoice
from ...core.database import SessionLocal
from app.api.invoices.models import Invoice
from ..suppliers import crud as suppliers_crud


def sanitize_total(value):
    """Extracts numeric value from string safely."""
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    # Remove commas and non-numeric characters except dot
    clean = re.sub(r"[^0-9.]", "", str(value))
    try:
        return float(clean) if clean else 0.0
    except ValueError:
        return 0.0


async def create_processing_invoice(
    db: AsyncSession,
    owner_id: int,
    vendor_name: str,
    invoice_type: str,
    company_id: int | None = None,
):
    inv = invoices_models.Invoice(
        owner_id=owner_id,
        company_id=company_id,
        vendor_name=vendor_name,
        is_processing=True,
        reviewed=False,
        type=invoice_type,
        file_path="",
        extraction_status="pending",
    )
    db.add(inv)
    await db.commit()
    await db.refresh(inv)
    return inv


async def update_invoice_after_processing(
    db: AsyncSession,
    invoice_id: int,
    parsed_fields: Dict[str, Optional[str]],
    file_url: str,
):
    """
    Replace placeholder data with parsed fields and mark as done.
    """
    stmt = select(invoices_models.Invoice).where(
        invoices_models.Invoice.id == invoice_id
    )
    result = await db.execute(stmt)
    invoice = result.scalar_one_or_none()
    if not invoice:
        return None
    invoice.file_path = file_url
    invoice.vendor_name = parsed_fields.get("vendor_name")
    invoice.invoice_number = parsed_fields.get("invoice_number")
    invoice.invoice_date = parsed_fields.get("invoice_date")
    invoice.trn_vat_number = parsed_fields.get("trn_vat_number")
    invoice.before_tax_amount = parsed_fields.get("before_tax_amount")
    invoice.tax_amount = parsed_fields.get("tax_amount")
    invoice.total = parsed_fields.get("total")
    invoice.remarks = parsed_fields.get("remarks")
    invoice.description = parsed_fields.get("description")
    invoice.line_items = parsed_fields.get("line_items")
    invoice.file_hash = parsed_fields.get("file_hash")
    invoice.is_duplicate = parsed_fields.get("is_duplicate")
    invoice.is_processing = False
    invoice.extraction_status = "success"
    if invoice.type == "expense" and invoice.vendor_name:
        supplier = await suppliers_crud.create_or_get_supplier(
            db,
            owner_id=invoice.owner_id,
            company_id=invoice.company_id,
            name=invoice.vendor_name,
            trn=invoice.trn_vat_number,
        )
        invoice.supplier_id = supplier.id

    await db.commit()
    await db.refresh(invoice)
    return invoice


async def mark_invoice_failed(
    db: AsyncSession, invoice_id: int, file_path: str | None = None
):
    stmt = select(invoices_models.Invoice).where(
        invoices_models.Invoice.id == invoice_id
    )
    result = await db.execute(stmt)
    invoice = result.scalar_one_or_none()
    if not invoice:
        return None

    invoice.is_processing = False
    invoice.remarks = "Parsing failed"
    invoice.extraction_status = "failed"
    if file_path:
        invoice.file_path = file_path
    await db.commit()
    return invoice


async def retry_invoice_extraction(
    db: AsyncSession, invoice_id: int, parsed_fields: Dict[str, Optional[str]]
):
    stmt = select(invoices_models.Invoice).where(
        invoices_models.Invoice.id == invoice_id
    )
    result = await db.execute(stmt)
    invoice = result.scalar_one_or_none()
    if not invoice:
        return None

    invoice.vendor_name = parsed_fields.get("vendor_name")
    invoice.invoice_number = parsed_fields.get("invoice_number")
    invoice.invoice_date = parsed_fields.get("invoice_date")
    invoice.trn_vat_number = parsed_fields.get("trn_vat_number")
    invoice.before_tax_amount = parsed_fields.get("before_tax_amount")
    invoice.tax_amount = parsed_fields.get("tax_amount")
    invoice.total = parsed_fields.get("total")
    invoice.description = parsed_fields.get("description")
    invoice.is_processing = False
    invoice.extraction_status = "success"

    await db.commit()
    await db.refresh(invoice)
    return invoice


async def create_invoice(
    db: AsyncSession,
    owner_id: int,
    file_path: str,
    fields: Dict[str, Optional[str]],
    company_id: int | None = None,
) -> invoices_models.Invoice:

    invoice_hash = fields.pop("file_hash", None)

    inv = invoices_models.Invoice(
        owner_id=owner_id,
        company_id=company_id,
        file_path=file_path,
        file_hash=invoice_hash,
        invoice_number=fields.get("invoice_number"),
        invoice_date=fields.get("invoice_date"),
        vendor_name=fields.get("vendor_name"),
        trn_vat_number=fields.get("trn_vat_number"),
        before_tax_amount=fields.get("before_tax_amount"),
        tax_amount=fields.get("tax_amount"),
        total=fields.get("total"),
        remarks=fields.get("remarks"),
        description=fields.get("description"),
        reviewed=False,
        type=fields.get("type") or None,
    )
    if inv.type == "expense" and inv.vendor_name:
        supplier = await suppliers_crud.create_or_get_supplier(
            db,
            owner_id=owner_id,
            company_id=company_id,
            name=inv.vendor_name,
            trn=inv.trn_vat_number,
        )
        inv.supplier_id = supplier.id
        await db.commit()

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


async def get_invoice_by_id(
    db: AsyncSession, invoice_id: int
) -> Optional[invoices_models.Invoice]:
    stmt = (
        select(invoices_models.Invoice)
        .where(
            invoices_models.Invoice.id == invoice_id,
        )
        .execution_options(populate_existing=False, autoflush=False, autocommit=False)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def list_invoices_by_owner(
    db: AsyncSession,
    owner_id: int,
    invoice_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
    search: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    ignore_pagination: bool = False,
):
    stmt = select(invoices_models.Invoice).where(
        invoices_models.Invoice.owner_id == owner_id,
        invoices_models.Invoice.batch_id.is_(None),
    )

    if invoice_type:
        stmt = stmt.where(invoices_models.Invoice.type == invoice_type)

    if search:
        stmt = stmt.where(
            or_(
                invoices_models.Invoice.vendor_name.ilike(f"%{search}%"),
                invoices_models.Invoice.invoice_number.ilike(f"%{search}%"),
                invoices_models.Invoice.invoice_date.ilike(f"%{search}%"),
                invoices_models.Invoice.trn_vat_number.ilike(f"%{search}%"),
                invoices_models.Invoice.description.ilike(f"%{search}%"),
            )
        )

    stmt = stmt.order_by(desc(invoices_models.Invoice.created_at))
    if not ignore_pagination:
        stmt = stmt.offset(offset).limit(limit)

    result = await db.execute(stmt)
    invoices = result.scalars().all()

    from_dt = datetime.strptime(from_date, "%Y-%m-%d") if from_date else None
    to_dt = datetime.strptime(to_date, "%Y-%m-%d") if to_date else None

    if from_dt or to_dt:
        filtered = []
        for inv in invoices:
            if not inv.invoice_date:
                filtered.append(inv)
                continue
            try:
                inv_date = datetime.strptime(inv.invoice_date, "%d-%m-%Y")
            except ValueError:
                continue
            if from_dt and inv_date < from_dt:
                continue
            if to_dt and inv_date > to_dt:
                continue
            filtered.append(inv)
        return filtered

    return invoices


async def list_invoices_to_review_by_owner(db: AsyncSession, owner_id: int):
    stmt = select(invoices_models.Invoice.id, invoices_models.Invoice.file_path).where(
        invoices_models.Invoice.owner_id == owner_id,
        invoices_models.Invoice.reviewed == False,
        invoices_models.Invoice.extraction_status == "success",
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
            "description",
            "type",
            "has_tax_note",
            "tax_note_type",
            "tax_note_amount",
        }
        for k, v in corrected_fields.items():
            if k in allowed:
                if k in {"before_tax_amount", "tax_amount", "total", "tax_note_amount"}:
                    if v is not None and v != "":
                        setattr(invoice, k, str(v))
                    else:
                        setattr(invoice, k, None)
                else:
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
        "description",
        "type",
        "has_tax_note",
        "tax_note_type",
        "tax_note_amount",
        "chart_of_account_id",
        "chart_of_account_name",
    }
    for k, v in corrected_fields.items():
        if k in allowed:
            if k in {"before_tax_amount", "tax_amount", "total", "tax_note_amount"}:
                setattr(invoice, k, str(v) if v not in (None, "") else None)
            else:
                setattr(invoice, k, v)

    if "has_tax_note" in corrected_fields and str(
        corrected_fields["has_tax_note"]
    ).lower() in ["false", "0", "none"]:
        invoice.tax_note_type = None
        invoice.tax_note_amount = None

    await db.commit()
    await db.refresh(invoice)
    return invoice


async def get_invoices_by_ids_and_owner(
    db: AsyncSession, ids: list[int], owner_id: int
):
    result = await db.execute(
        select(invoices_models.Invoice).where(
            invoices_models.Invoice.id.in_(ids),
            invoices_models.Invoice.owner_id == owner_id,
        )
    )
    return result.scalars().all()


async def delete_invoice(db: AsyncSession, invoice_id: int, owner_id: int) -> bool:
    await db.execute(
        delete(invoices_models.Invoice).where(
            invoices_models.Invoice.id == invoice_id,
            invoices_models.Invoice.owner_id == owner_id,
        )
    )
    await db.commit()
    return True


async def delete_invoices(db: AsyncSession, ids: list[int], owner_id: int) -> int:
    result = await db.execute(
        delete(invoices_models.Invoice)
        .where(
            invoices_models.Invoice.id.in_(ids),
            invoices_models.Invoice.owner_id == owner_id,
        )
        .returning(invoices_models.Invoice.id)
    )

    deleted = result.scalars().all()
    await db.commit()
    return len(deleted)


async def run_invoice_extraction(
    invoice_id: int,
    content: bytes,
    ext: str,
    invoice_type: str,
    file_url: str,
    file_hash: str,
    is_duplicate: bool,
):
    """
    Run the invoice extraction process asynchronously for a given invoice ID.
    Uses SessionLocal from your database.py for correct async context management.
    """
    async with SessionLocal() as db:
        try:
            parsed_fields = await asyncio.get_event_loop().run_in_executor(
                None, process_invoice, content, ext, invoice_type
            )
            parsed_fields["type"] = invoice_type
            parsed_fields["file_hash"] = file_hash
            parsed_fields["is_duplicate"] = is_duplicate

            field_values = [
                parsed_fields.get("vendor_name"),
                parsed_fields.get("invoice_number"),
                parsed_fields.get("invoice_date"),
                parsed_fields.get("trn_vat_number"),
                parsed_fields.get("before_tax_amount"),
                parsed_fields.get("tax_amount"),
                parsed_fields.get("total"),
            ]
            all_null = all(v in [None, ""] for v in field_values)

            if all_null:
                await mark_invoice_failed(db, invoice_id, file_url)
                print(f"⚠️ Invoice {invoice_id} extraction failed — all fields empty.")
                return

            await update_invoice_after_processing(
                db, invoice_id, parsed_fields, file_url
            )

            print(f"✅ Invoice {invoice_id} extraction completed successfully.")

        except Exception as e:
            print(f"❌ Background extraction failed for invoice {invoice_id}: {e}")
            await mark_invoice_failed(db, invoice_id, file_url)


async def get_invoice_analytics(db: AsyncSession, owner_id: int):
    """Returns analytics summary for invoices owned by the user."""

    # Fetch all invoices once and sanitize totals in Python
    invoices_query = select(
        invoices_models.Invoice.type,
        invoices_models.Invoice.total,
        invoices_models.Invoice.vendor_name,
    ).where(invoices_models.Invoice.owner_id == owner_id)
    result = await db.execute(invoices_query)
    invoices = result.all()

    if not invoices:
        return {
            "sales_count": 0,
            "total_sales_amount": 0.0,
            "expense_count": 0,
            "total_expense_amount": 0.0,
            "total_invoices": 0,
            "num_customers": 0,
            "num_vendors": 0,
            "top_customer": {"name": None, "amount": 0.0},
            "top_vendor": {"name": None, "amount": 0.0},
        }

    sales = []
    expenses = []

    for inv in invoices:
        amount = sanitize_total(inv.total)
        if inv.type == "sales":
            sales.append((inv.vendor_name, amount))
        elif inv.type == "expense":
            expenses.append((inv.vendor_name, amount))

    # Summaries
    total_sales_amount = sum(a for _, a in sales)
    total_expense_amount = sum(a for _, a in expenses)

    from collections import Counter

    # Top customer/vendor
    customer_totals = Counter()
    for name, amount in sales:
        customer_totals[name] += amount
    top_customer = customer_totals.most_common(1)[0] if customer_totals else (None, 0)

    vendor_totals = Counter()
    for name, amount in expenses:
        vendor_totals[name] += amount
    top_vendor = vendor_totals.most_common(1)[0] if vendor_totals else (None, 0)

    return {
        "sales_count": len(sales),
        "total_sales_amount": round(total_sales_amount, 2),
        "expense_count": len(expenses),
        "total_expense_amount": round(total_expense_amount, 2),
        "total_invoices": len(invoices),
        "num_customers": len(set(n for n, _ in sales if n)),
        "num_vendors": len(set(n for n, _ in expenses if n)),
        "top_customer": {"name": top_customer[0], "amount": round(top_customer[1], 2)},
        "top_vendor": {"name": top_vendor[0], "amount": round(top_vendor[1], 2)},
    }


async def update_invoice_qb_id(db: AsyncSession, invoice_id: int, qb_id: str):
    stmt = (
        update(Invoice)
        .where(Invoice.id == invoice_id)
        .values(qb_id=qb_id)
        .execution_options(synchronize_session=False)
    )
    await db.execute(stmt)
    await db.commit()


async def list_invoices_by_company(
    db: AsyncSession,
    company_id: int,
    invoice_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
    search: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    ignore_pagination: bool = False,
):
    stmt = select(invoices_models.Invoice).where(
        invoices_models.Invoice.company_id == company_id,
        invoices_models.Invoice.batch_id.is_(None),
    )

    if invoice_type:
        stmt = stmt.where(invoices_models.Invoice.type == invoice_type)

    if search:
        stmt = stmt.where(
            or_(
                invoices_models.Invoice.vendor_name.ilike(f"%{search}%"),
                invoices_models.Invoice.invoice_number.ilike(f"%{search}%"),
                invoices_models.Invoice.invoice_date.ilike(f"%{search}%"),
                invoices_models.Invoice.trn_vat_number.ilike(f"%{search}%"),
                invoices_models.Invoice.description.ilike(f"%{search}%"),
            )
        )

    stmt = stmt.order_by(desc(invoices_models.Invoice.created_at))
    if not ignore_pagination:
        stmt = stmt.offset(offset).limit(limit)

    result = await db.execute(stmt)
    invoices = result.scalars().all()

    from_dt = datetime.strptime(from_date, "%Y-%m-%d") if from_date else None
    to_dt = datetime.strptime(to_date, "%Y-%m-%d") if to_date else None

    if from_dt or to_dt:
        filtered = []
        for inv in invoices:
            if not inv.invoice_date:
                filtered.append(inv)
                continue
            try:
                inv_date = datetime.strptime(inv.invoice_date, "%d-%m-%Y")
            except ValueError:
                continue
            if from_dt and inv_date < from_dt:
                continue
            if to_dt and inv_date > to_dt:
                continue
            filtered.append(inv)
        return filtered

    return invoices


async def get_invoice_by_id_and_company(
    db: AsyncSession, invoice_id: int, company_id: int
):
    stmt = select(invoices_models.Invoice).where(
        invoices_models.Invoice.id == invoice_id,
        invoices_models.Invoice.company_id == company_id,
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()
