from sqlalchemy import select, func, cast, Numeric
from sqlalchemy.orm import selectinload
from decimal import Decimal, InvalidOperation

from .models import Report
from ..invoices.models import Invoice
from ..user_docs.models import UserDocs
from ..batches import models as batch_models


def _to_decimal(value):
    """Safely convert strings or None to Decimal."""
    try:
        return Decimal(str(value or "0").replace(",", "").strip())
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


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

        sales_invoices = [i for i in invoices if i["type"] == "sales"]
        expense_invoices = [i for i in invoices if i["type"] == "expense"]

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
        total_vat_output = (
            sum([t.tax_sum for t in tax_totals if t.type == "sales"]) or 0
        )
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
        standard_rated_sales = (
            sum([s.std_total for s in std_totals if s.type == "sales"]) or 0
        )

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
