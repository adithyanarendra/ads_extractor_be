from sqlalchemy import select, func, cast, Numeric
from .models import Report
from ..invoices.models import Invoice
from ..user_docs.models import UserDocs


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

        return {
            "ok": True,
            "message": "VAT summary fetched successfully",
            "error": None,
            "data": {
                "company_details": company_details,
                "sales_invoices": sales_invoices,
                "expense_invoices": expense_invoices,
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
