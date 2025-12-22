from sqlalchemy import select, func, cast, Numeric
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from datetime import datetime
from decimal import Decimal, InvalidOperation

from .models import Report
from ..invoices.models import Invoice
from ..user_docs.models import UserDocs
from ..sales.models import SalesInvoice, SalesTaxCreditNote
from ..batches import models as batch_models


def _to_decimal(value):
    """Safely convert strings or None to Decimal."""
    try:
        return Decimal(str(value or "0").replace(",", "").strip())
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def _parse_date(d: str):
    try:
        return datetime.strptime(d, "%Y-%m-%d")
    except:
        return None


def _safe_float(v):
    try:
        return float(str(v).replace(",", "").strip())
    except:
        return 0.0


def _to_date_from_uploaded_format(date_str: str):
    """Uploaded invoices store invoice_date as DD-MM-YYYY string."""
    try:
        return datetime.strptime(date_str, "%d-%m-%Y")
    except:
        return None


async def get_vat_summary(db, user_id: int):
    try:
        vat_doc = await db.execute(
            select(
                UserDocs.vat_legal_name_arabic,
                UserDocs.vat_legal_name_english,
                UserDocs.vat_tax_registration_number,
            ).where(
                UserDocs.user_id == user_id,
                UserDocs.vat_tax_registration_number.isnot(None),
            )
        )
        company = vat_doc.fetchone()

        company_details = {
            "vat_legal_name_arabic": company.vat_legal_name_arabic if company else None,
            "vat_legal_name_english": (
                company.vat_legal_name_english if company else None
            ),
            "vat_tax_registration_number": (
                company.vat_tax_registration_number if company else None
            ),
        }

        if not company:
            return {
                "ok": False,
                "message": "VAT certificate not found for user",
                "error": "VAT certificate missing",
                "data": None,
            }

        invoice_query = select(
            Invoice.invoice_number,
            Invoice.invoice_date,
            Invoice.vendor_name,
            Invoice.trn_vat_number,
            Invoice.before_tax_amount,
            Invoice.tax_amount,
            Invoice.total,
            Invoice.remarks,
            Invoice.type,
        ).where(Invoice.owner_id == user_id, Invoice.reviewed == True)

        invoices = (await db.execute(invoice_query)).mappings().all()

        uploaded_sales = [i for i in invoices if i["type"] == "sales"]
        expense_invoices = [i for i in invoices if i["type"] == "expense"]

        gen_sales_q = await db.execute(
            select(
                SalesInvoice.invoice_number,
                SalesInvoice.invoice_date,
                SalesInvoice.customer_name,
                SalesInvoice.customer_trn,
                SalesInvoice.subtotal,
                SalesInvoice.total_vat,
                SalesInvoice.total,
                SalesInvoice.notes,
            ).where(
                SalesInvoice.owner_id == user_id,
                SalesInvoice.is_deleted == False,
            )
        )
        generated_sales_rows = gen_sales_q.mappings().all()
        generated_sales = [
            {
                "invoice_number": r["invoice_number"],
                "invoice_date": r["invoice_date"],
                "vendor_name": r["customer_name"],
                "trn_vat_number": r["customer_trn"],
                "before_tax_amount": str(r["subtotal"] or 0),
                "tax_amount": str(r["total_vat"] or 0),
                "total": str(r["total"] or 0),
                "remarks": r["notes"],
                "type": "sales",
            }
            for r in generated_sales_rows
        ]

        cn_q = await db.execute(
            select(
                SalesTaxCreditNote.credit_note_number,
                SalesTaxCreditNote.credit_note_date,
                SalesTaxCreditNote.customer_name,
                SalesTaxCreditNote.customer_trn,
                SalesTaxCreditNote.subtotal,
                SalesTaxCreditNote.total_vat,
                SalesTaxCreditNote.total,
                SalesTaxCreditNote.notes,
                SalesTaxCreditNote.reference_invoice_id,
            ).where(SalesTaxCreditNote.owner_id == user_id)
        )
        credit_note_rows = cn_q.mappings().all()
        credit_notes_as_sales = [
            {
                "invoice_number": r["credit_note_number"],
                "invoice_date": r["credit_note_date"],
                "vendor_name": r["customer_name"],
                "trn_vat_number": r["customer_trn"],
                "before_tax_amount": str(r["subtotal"] or 0),
                "tax_amount": str(r["total_vat"] or 0),
                "total": str(r["total"] or 0),
                "remarks": r["notes"]
                or f"Credit note against invoice {r['reference_invoice_id']}",
                "type": "sales",
            }
            for r in credit_note_rows
        ]

        sales_invoices = uploaded_sales + generated_sales + credit_notes_as_sales

        # ---- VAT Calculations ----
        tax_sum_query = await db.execute(
            select(
                func.sum(cast(Invoice.tax_amount, Numeric)).label("tax_sum"),
                Invoice.type,
            )
            .where(Invoice.owner_id == user_id, Invoice.reviewed == True)
            .group_by(Invoice.type)
        )

        tax_totals = tax_sum_query.all()
        total_vat_input = (
            sum([t.tax_sum for t in tax_totals if t.type == "expense"]) or 0
        )
        uploaded_vat_output = sum([t.tax_sum for t in tax_totals if t.type == "sales"]) or 0

        generated_vat_output_q = await db.execute(
            select(func.sum(SalesInvoice.total_vat)).where(
                SalesInvoice.owner_id == user_id,
                SalesInvoice.is_deleted == False,
            )
        )
        generated_vat_output = generated_vat_output_q.scalar() or 0

        credit_vat_output_q = await db.execute(
            select(func.sum(SalesTaxCreditNote.total_vat)).where(
                SalesTaxCreditNote.owner_id == user_id
            )
        )
        credit_vat_output = credit_vat_output_q.scalar() or 0

        total_vat_output = uploaded_vat_output + generated_vat_output + credit_vat_output
        total_vat_to_pay = total_vat_output - total_vat_input

        std_totals_query = await db.execute(
            select(
                func.sum(cast(Invoice.before_tax_amount, Numeric)).label("std_total"),
                Invoice.type,
            )
            .where(Invoice.owner_id == user_id, Invoice.reviewed == True)
            .group_by(Invoice.type)
        )

        std_totals = std_totals_query.all()
        standard_rated_expense = (
            sum([s.std_total for s in std_totals if s.type == "expense"]) or 0
        )
        uploaded_standard_sales = sum([s.std_total for s in std_totals if s.type == "sales"]) or 0

        generated_standard_sales_q = await db.execute(
            select(func.sum(SalesInvoice.subtotal)).where(
                SalesInvoice.owner_id == user_id,
                SalesInvoice.is_deleted == False,
            )
        )
        generated_standard_sales = generated_standard_sales_q.scalar() or 0

        credit_standard_sales_q = await db.execute(
            select(func.sum(SalesTaxCreditNote.subtotal)).where(
                SalesTaxCreditNote.owner_id == user_id
            )
        )
        credit_standard_sales = credit_standard_sales_q.scalar() or 0

        standard_rated_sales = uploaded_standard_sales + generated_standard_sales + credit_standard_sales

        return {
            "ok": True,
            "message": "VAT summary fetched successfully",
            "error": None,
            "data": {
                "company_details": company_details,
                "sales_invoices": sales_invoices,
                "expense_invoices": expense_invoices,
                "standard_rated_expense": str(standard_rated_expense),
                "standard_rated_sales": str(standard_rated_sales),
                "total_vat_input": str(total_vat_input),
                "total_vat_output": str(total_vat_output),
                "total_vat_to_pay": str(total_vat_to_pay),
            },
        }

    except Exception as e:
        return {
            "ok": False,
            "message": "Unexpected error while generating VAT summary",
            "error": str(e),
            "data": None,
        }


async def get_vat_summary_by_batch(db, user_id: int, batch_id: int):
    try:
        vat_doc = await db.execute(
            select(
                UserDocs.vat_legal_name_arabic,
                UserDocs.vat_legal_name_english,
                UserDocs.vat_tax_registration_number,
            ).where(
                UserDocs.user_id == user_id,
                UserDocs.vat_tax_registration_number.isnot(None),
            )
        )
        company = vat_doc.fetchone()

        if not company:
            return {
                "ok": False,
                "message": "VAT certificate not found for user",
                "error": "VAT_CERTIFICATE_MISSING",
                "data": None,
            }

        batch_result = await db.execute(
            select(batch_models.Batch)
            .options(
                selectinload(batch_models.Batch.invoices),
                selectinload(batch_models.Batch.children).selectinload(
                    batch_models.Batch.invoices
                ),
                selectinload(batch_models.Batch.parent),
            )
            .where(
                batch_models.Batch.id == batch_id,
                batch_models.Batch.owner_id == user_id,
            )
        )
        batch = batch_result.scalars().unique().one_or_none()

        if not batch:
            return {
                "ok": False,
                "message": "Batch not found",
                "error": "NOT_FOUND",
                "data": None,
            }

        vat_period = batch.parent.name if batch.parent else batch.name

        all_invoices = list(batch.invoices or [])
        for child in batch.children or []:
            all_invoices.extend(child.invoices or [])

        if not all_invoices:
            return {
                "ok": False,
                "message": "No invoices inside the batch",
                "error": "EMPTY_BATCH",
                "data": None,
            }

        invoice_ids = [i.id for i in all_invoices]

        invoice_query = select(
            Invoice.invoice_number,
            Invoice.invoice_date,
            Invoice.vendor_name,
            Invoice.trn_vat_number,
            Invoice.before_tax_amount,
            Invoice.tax_amount,
            Invoice.total,
            Invoice.remarks,
            Invoice.type,
            Invoice.source_sales_invoice_id,
            Invoice.has_tax_note,
            Invoice.tax_note_type,
            Invoice.tax_note_amount,
        ).where(
            Invoice.owner_id == user_id,
            Invoice.reviewed == True,
            Invoice.id.in_(invoice_ids),
        )
        result = await db.execute(invoice_query)

        invoices = (await db.execute(invoice_query)).mappings().all()

        # Include sales credit notes that reference generated sales invoices in this batch.
        sales_source_ids = [
            i.get("source_sales_invoice_id")
            for i in invoices
            if i.get("type") == "sales" and i.get("source_sales_invoice_id") is not None
        ]

        if sales_source_ids:
            cn_q = await db.execute(
                select(
                    SalesTaxCreditNote.credit_note_number,
                    SalesTaxCreditNote.credit_note_date,
                    SalesTaxCreditNote.customer_name,
                    SalesTaxCreditNote.customer_trn,
                    SalesTaxCreditNote.subtotal,
                    SalesTaxCreditNote.total_vat,
                    SalesTaxCreditNote.total,
                    SalesTaxCreditNote.notes,
                    SalesTaxCreditNote.reference_invoice_id,
                ).where(
                    SalesTaxCreditNote.owner_id == user_id,
                    SalesTaxCreditNote.reference_invoice_id.in_(sales_source_ids),
                )
            )
            credit_note_rows = cn_q.mappings().all()

            credit_notes_as_sales = [
                {
                    "invoice_number": r["credit_note_number"],
                    "invoice_date": (
                        r["credit_note_date"].strftime("%d-%m-%Y")
                        if r["credit_note_date"]
                        else None
                    ),
                    "vendor_name": r["customer_name"],
                    "trn_vat_number": r["customer_trn"],
                    "before_tax_amount": str(r["subtotal"] or 0),
                    "tax_amount": str(r["total_vat"] or 0),
                    "total": str(r["total"] or 0),
                    "remarks": r["notes"]
                    or f"Sales credit note against sales invoice {r['reference_invoice_id']}",
                    "type": "sales",
                    "source_sales_invoice_id": None,
                    "has_tax_note": False,
                    "tax_note_type": None,
                    "tax_note_amount": None,
                }
                for r in credit_note_rows
            ]

            invoices = invoices + credit_notes_as_sales

        if not invoices:
            return {
                "ok": False,
                "message": "No verified invoices found inside the batch",
                "error": "EMPTY_BATCH",
                "data": None,
            }

        total_vat_input = Decimal("0")
        total_vat_output = Decimal("0")
        standard_rated_sales = Decimal("0")
        standard_rated_expense = Decimal("0")

        for inv in invoices:
            inv_type = inv.get("type")
            tax_amount = _to_decimal(inv.get("tax_amount"))
            before_tax_amount = _to_decimal(inv.get("before_tax_amount"))
            has_note = inv.get("has_tax_note", False)
            note_type = (inv.get("tax_note_type") or "").lower().strip()
            note_amount = _to_decimal(inv.get("tax_note_amount"))

            if inv_type == "sales":
                total_vat_output += tax_amount
                standard_rated_sales += before_tax_amount
            elif inv_type == "expense":
                total_vat_input += tax_amount
                standard_rated_expense += before_tax_amount

            if has_note and note_type in ("credit", "debit"):
                if inv_type == "sales":
                    if note_type == "credit":
                        total_vat_output -= note_amount
                    elif note_type == "debit":
                        total_vat_output += note_amount
                elif inv_type == "expense":
                    if note_type == "credit":
                        total_vat_input -= note_amount
                    elif note_type == "debit":
                        total_vat_input += note_amount

        total_vat_to_pay = total_vat_output - total_vat_input

        return {
            "ok": True,
            "message": f"VAT summary fetched successfully for batch '{batch.name}'",
            "error": None,
            "data": {
                "batch_id": batch.id,
                "batch_name": batch.name,
                "invoice_count": len(invoice_ids),
                "company_details": {
                    "vat_legal_name_arabic": company.vat_legal_name_arabic,
                    "vat_legal_name_english": company.vat_legal_name_english,
                    "vat_tax_registration_number": company.vat_tax_registration_number,
                    "vat_period": vat_period,
                },
                "vat_period": vat_period,
                "sales_invoices": [i for i in invoices if i["type"] == "sales"],
                "expense_invoices": [i for i in invoices if i["type"] == "expense"],
                "standard_rated_expense": str(standard_rated_expense),
                "standard_rated_sales": str(standard_rated_sales),
                "total_vat_input": str(total_vat_input),
                "total_vat_output": str(total_vat_output),
                "total_vat_to_pay": str(total_vat_to_pay),
            },
        }

    except Exception as e:
        return {
            "ok": False,
            "message": "Unexpected error while generating VAT batch summary",
            "error": str(e),
            "data": None,
        }


async def create_report(db, user_id: int, report_name: str, type: str, file_path: str):
    try:
        existing = await db.execute(
            select(Report).where(
                Report.user_id == user_id, Report.report_name == report_name
            )
        )
        if existing.scalar():
            return {
                "ok": False,
                "message": "Report name already exists",
                "error": "DUPLICATE_NAME",
                "data": None,
            }

        report = Report(
            user_id=user_id,
            report_name=report_name,
            type=type,
            file_path=file_path,
        )
        db.add(report)
        await db.commit()
        await db.refresh(report)

        return {
            "ok": True,
            "message": "Report saved successfully",
            "error": None,
            "data": report,
        }

    except Exception as e:
        await db.rollback()
        return {
            "ok": False,
            "message": "Failed to save report",
            "error": str(e),
            "data": None,
        }


async def get_all_reports(db, user_id: int):
    q = await db.execute(
        select(Report.id, Report.report_name, Report.type, Report.uploaded_at)
        .where(Report.user_id == user_id)
        .order_by(Report.uploaded_at.desc())
    )
    rows = q.all()
    return rows


async def get_report(db, report_id: int, user_id: int):
    q = await db.execute(
        select(Report).where(Report.id == report_id, Report.user_id == user_id)
    )
    return q.scalar_one_or_none()


async def generate_pnl_report(
    db: AsyncSession, user_id: int, start_date: str, end_date: str
):
    start_dt = _parse_date(start_date)
    end_dt = _parse_date(end_date)

    if not start_dt or not end_dt:
        return {
            "ok": False,
            "message": "Invalid date format. Expected YYYY-MM-DD",
            "error": "INVALID_DATES",
            "data": None,
        }

    start_date_only = start_dt.date()
    end_date_only = end_dt.date()

    q = await db.execute(
        select(
            UserDocs.vat_legal_name_english,
            UserDocs.vat_legal_name_arabic,
            UserDocs.vat_tax_registration_number,
        ).where(
            UserDocs.user_id == user_id,
            UserDocs.vat_tax_registration_number.isnot(None),
        )
    )
    doc = q.fetchone()

    if not doc:
        return {
            "ok": False,
            "message": "VAT certificate not found for this user",
            "error": "VAT_CERTIFICATE_MISSING",
            "data": None,
        }

    company_details = {
        "vat_legal_name_english": doc.vat_legal_name_english,
        "vat_legal_name_arabic": doc.vat_legal_name_arabic,
        "vat_tax_registration_number": doc.vat_tax_registration_number,
    }

    inv_q = await db.execute(
        select(
            Invoice.invoice_number,
            Invoice.invoice_date,
            Invoice.vendor_name,
            Invoice.trn_vat_number,
            Invoice.before_tax_amount,
            Invoice.tax_amount,
            Invoice.total,
            Invoice.type,
            Invoice.remarks,
        ).where(
            Invoice.owner_id == user_id,
            Invoice.reviewed == True,
        )
    )

    all_uploaded = inv_q.mappings().all()
    filtered_uploaded = []

    for inv in all_uploaded:
        dt = _to_date_from_uploaded_format(inv["invoice_date"])
        if not dt:
            continue

        dt = dt.date()

        if start_date_only <= dt <= end_date_only:
            filtered_uploaded.append(inv)

    uploaded_sales = [i for i in filtered_uploaded if i["type"] == "sales"]
    uploaded_expenses = [i for i in filtered_uploaded if i["type"] == "expense"]

    sales_q = await db.execute(
        select(
            SalesInvoice.invoice_number,
            SalesInvoice.invoice_date,
            SalesInvoice.customer_name,
            SalesInvoice.customer_trn,
            SalesInvoice.total,
            SalesInvoice.notes,
            SalesInvoice.is_deleted,
        ).where(
            SalesInvoice.owner_id == user_id,
            SalesInvoice.is_deleted == False,
        )
    )
    all_generated = sales_q.mappings().all()

    generated_sales = []

    for s in all_generated:
        dt = s.get("invoice_date")
        if not dt:
            continue

        try:
            dt_date = dt.date()
        except:
            continue

        if start_date_only <= dt_date <= end_date_only:
            generated_sales.append(s)

    credit_q = await db.execute(
        select(
            SalesTaxCreditNote.credit_note_number,
            SalesTaxCreditNote.credit_note_date,
            SalesTaxCreditNote.customer_name,
            SalesTaxCreditNote.customer_trn,
            SalesTaxCreditNote.total,
            SalesTaxCreditNote.notes,
            SalesTaxCreditNote.reference_invoice_id,
        ).where(SalesTaxCreditNote.owner_id == user_id)
    )
    all_credit_notes = credit_q.mappings().all()

    credit_notes = []
    for n in all_credit_notes:
        dt = n.get("credit_note_date")
        if not dt:
            continue
        try:
            dt_date = dt.date()
        except:
            continue
        if start_date_only <= dt_date <= end_date_only:
            credit_notes.append(n)

    total_sales_uploaded = sum(_safe_float(i["total"]) for i in uploaded_sales)
    total_sales_generated = sum(_safe_float(i["total"]) for i in generated_sales)
    total_credit_notes = sum(_safe_float(i["total"]) for i in credit_notes)
    total_expenses = sum(_safe_float(i["total"]) for i in uploaded_expenses)

    total_sales = total_sales_uploaded + total_sales_generated + total_credit_notes
    net_profit = total_sales - total_expenses

    return {
        "ok": True,
        "message": "P&L Summary generated",
        "error": None,
        "data": {
            "isPnl": True,
            "company_details": company_details,
            "period": {"start_date": start_date, "end_date": end_date},
            "sales_count": len(uploaded_sales) + len(generated_sales) + len(credit_notes),
            "sales_total": total_sales,
            "expenses_count": len(uploaded_expenses),
            "expenses_total": total_expenses,
            "net_profit": net_profit,
        },
    }
