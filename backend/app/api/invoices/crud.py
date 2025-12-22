from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import update, delete, or_, desc, func, select
import re
from typing import Optional, Dict
from . import models as invoices_models
from datetime import datetime, date
import asyncio
from ...utils.ocr_parser import process_invoice
from ...core.database import SessionLocal
from app.api.invoices.models import Invoice
from ..suppliers import crud as suppliers_crud
from ..users.crud import get_connection_status
from ..batches import crud as batches_crud


def sanitize_total(value):
    """Extracts numeric value from string safely."""
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
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
    invoice.file_hash = parsed_fields.get("file_hash")
    invoice.is_duplicate = parsed_fields.get("is_duplicate")
    invoice.is_processing = False
    invoice.extraction_status = "success"

    raw_line_items = parsed_fields.get("line_items")

    if (not raw_line_items or len(raw_line_items) == 0) and invoice.type == "expense":

        try:
            before_tax = float(parsed_fields.get("before_tax_amount") or 0)
            tax_amt = float(parsed_fields.get("tax_amount") or 0)
            tot_amt = float(parsed_fields.get("total") or 0)
        except ValueError:
            before_tax, tax_amt, tot_amt = 0.0, 0.0, 0.0

        VAT_RATE = 0.05

        default_line_item = {
            "description": "Standard Rated Expenses",
            "amount": f"{before_tax:.2f}",
            "tax": f"{tax_amt:.2f}",
            "total": f"{tot_amt:.2f}",
            "quantity": 1,
            "tax_rate": f"{int(VAT_RATE * 100)}%",
        }

        invoice.line_items = [default_line_item]
    else:
        invoice.line_items = raw_line_items

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
    invoice = result.scalar_one_or_none()

    if invoice and invoice.source_sales_invoice_id is not None:
        return None

    return invoice


async def list_archived_expense_invoices(
    db: AsyncSession,
    owner_id: int,
    search: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
):
    Invoice = invoices_models.Invoice

    invoice_date_sql = func.to_date(Invoice.invoice_date, "DD-MM-YYYY")

    stmt = select(Invoice).where(
        Invoice.owner_id == owner_id,
        Invoice.is_deleted == False,
        Invoice.type == "expense",
    )

    stmt = stmt.where(Invoice.invoice_date.op("~")(r"^\d{2}-\d{2}-\d{4}$"))

    if search:
        like = f"%{search.lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(Invoice.vendor_name).ilike(like),
                func.lower(Invoice.invoice_number).ilike(like),
                func.lower(Invoice.trn_vat_number).ilike(like),
                func.lower(Invoice.description).ilike(like),
            )
        )

    if from_date:
        stmt = stmt.where(invoice_date_sql >= from_date)

    if to_date:
        stmt = stmt.where(invoice_date_sql <= to_date)

    stmt = stmt.order_by(desc(Invoice.created_at))
    result = await db.execute(stmt)
    invoices = result.scalars().all()

    return invoices


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
        invoices_models.Invoice.is_deleted == False,
        or_(Invoice.is_published == False, Invoice.is_published.is_(None)),
        invoices_models.Invoice.source_sales_invoice_id.is_(None),
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
        Invoice.is_deleted == False,
        Invoice.source_sales_invoice_id.is_(None),
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
    if invoice.source_sales_invoice_id is not None:
        return None

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
            "chart_of_account_id",
            "chart_of_account_name",
            "is_paid",
        }
        for k, v in corrected_fields.items():
            if k in allowed:

                # Numeric values stored as VARCHAR in DB
                if k in {"before_tax_amount", "tax_amount", "total", "tax_note_amount"}:
                    if v is not None and v != "":
                        setattr(invoice, k, str(v))  # keep feature branch behavior
                    else:
                        setattr(invoice, k, None)

                else:
                    setattr(invoice, k, v)

        if "chart_of_account_id" in corrected_fields:
            invoice.chart_of_account_id = corrected_fields["chart_of_account_id"]

        if "chart_of_account_name" in corrected_fields:
            invoice.chart_of_account_name = corrected_fields["chart_of_account_name"]
        qb_connected = await get_connection_status(db, owner_id, "is_qb_connected")
        invoice.accounting_software = "qb" if qb_connected else "zb"
    await db.commit()
    await db.refresh(invoice)
    return invoice


async def set_invoice_coa(
    db: AsyncSession,
    invoice_id: int,
    owner_id: int,
    chart_of_account_id: str,
    chart_of_account_name: Optional[str] = None,
):
    invoice = await get_invoice_by_id_and_owner(db, invoice_id, owner_id)
    if not invoice:
        return False

    invoice.chart_of_account_id = chart_of_account_id
    invoice.chart_of_account_name = chart_of_account_name
    invoice.accounting_software = "zb"
    await db.commit()
    await db.refresh(invoice)
    return True


async def edit_invoice(
    db: AsyncSession,
    invoice_id: int,
    owner_id: int,
    corrected_fields: Dict[str, Optional[str]],
):
    invoice = await get_invoice_by_id_and_owner(db, invoice_id, owner_id)

    if invoice.source_sales_invoice_id is not None:
        return None

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
        "is_paid",
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
            print("processing invoice")
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
            print("calling update invoice function")
            await update_invoice_after_processing(
                db, invoice_id, parsed_fields, file_url
            )

            print(f"✅ Invoice {invoice_id} extraction completed successfully.")

        except Exception as e:
            print(f"❌ Background extraction failed for invoice {invoice_id}: {e}")
            await mark_invoice_failed(db, invoice_id, file_url)


async def get_invoice_analytics(db: AsyncSession, owner_id: int):
    result = await db.execute(
        select(
            invoices_models.Invoice.type,
            invoices_models.Invoice.total,
            invoices_models.Invoice.vendor_name,
        ).where(
            invoices_models.Invoice.owner_id == owner_id,
            Invoice.is_deleted == False,
            Invoice.source_sales_invoice_id.is_(None),
        )
    )

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
        .values(qb_id=qb_id, is_published=True, accounting_software="qb")
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
        invoices_models.Invoice.is_published == False,
        Invoice.is_deleted == False,
        Invoice.source_sales_invoice_id.is_(None),
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


async def mark_invoice_as_published(db: AsyncSession, invoice_id: int):
    stmt = (
        update(Invoice)
        .where(Invoice.id == invoice_id)
        .values(is_published=True)
        .execution_options(synchronize_session=False)
    )
    await db.execute(stmt)
    await db.commit()


async def soft_delete_invoice(
    db: AsyncSession, invoice_id: int, deleted_by: int
) -> bool:
    stmt = select(invoices_models.Invoice).where(
        invoices_models.Invoice.id == invoice_id
    )
    result = await db.execute(stmt)
    invoice = result.scalar_one_or_none()
    if not invoice:
        return False
    invoice.is_deleted = True
    invoice.deleted_at = datetime.utcnow()
    invoice.deleted_by = deleted_by
    await db.commit()
    await db.refresh(invoice)
    return True


async def reset_invoices_on_software_switch(
    db: AsyncSession, user_id: int, connected_software: str
):
    """
    Reset all invoices for the user that belong to the OTHER accounting software.
    """

    if connected_software not in {"qb", "zb"}:
        raise ValueError("connected_software must be 'qb' or 'zb'")

    stmt = (
        update(Invoice)
        .where(
            Invoice.owner_id == user_id,
            Invoice.is_published == False,
            or_(
                Invoice.accounting_software.is_(None),
                Invoice.accounting_software != connected_software,
            ),
        )
        .values(
            accounting_software=None,
            chart_of_account_id=None,
            chart_of_account_name=None,
        )
        .execution_options(synchronize_session="fetch")
    )

    await db.execute(stmt)
    await db.commit()

    return True


async def list_unpaid_expense_invoices(db: AsyncSession, owner_id: int):
    Invoice = invoices_models.Invoice

    stmt = (
        select(Invoice)
        .where(
            Invoice.owner_id == owner_id,
            Invoice.type == "expense",
            Invoice.is_deleted == False,
            Invoice.is_paid == False,
        )
        .order_by(desc(Invoice.created_at))
    )

    result = await db.execute(stmt)
    return result.scalars().all()


import hashlib


async def create_invoice_from_sales(
    db: AsyncSession,
    owner_id: int,
    sales_invoice,
):
    existing = await get_invoice_by_sales_id(db, sales_invoice.id)
    if existing:
        return existing

    hash_input = f"sales:{owner_id}:{sales_invoice.id}"
    file_hash = hashlib.sha256(hash_input.encode()).hexdigest()

    invoice = Invoice(
        owner_id=owner_id,
        type="sales",
        source_sales_invoice_id=sales_invoice.id,
        file_path=None,
        file_hash=file_hash,
        invoice_number=sales_invoice.invoice_number,
        invoice_date=(
            sales_invoice.invoice_date.strftime("%d-%m-%Y")
            if sales_invoice.invoice_date
            else None
        ),
        vendor_name=sales_invoice.customer_name,
        trn_vat_number=sales_invoice.customer_trn,
        before_tax_amount=str(sales_invoice.subtotal),
        tax_amount=str(sales_invoice.total_vat),
        total=str(sales_invoice.total),
        reviewed=True,
        is_processing=False,
        extraction_status="success",
    )

    db.add(invoice)
    await db.flush()
    batch_id = await batches_crud.find_matching_batch_for_invoice(
        db,
        owner_id,
        sales_invoice.invoice_date,  # datetime
    )

    if batch_id:
        invoice.batch_id = batch_id

    await db.commit()
    await db.refresh(invoice)

    return invoice


async def get_invoice_by_sales_id(db: AsyncSession, sales_invoice_id: int):
    res = await db.execute(
        select(Invoice).where(Invoice.source_sales_invoice_id == sales_invoice_id)
    )
    return res.scalar_one_or_none()
