from rapidfuzz import fuzz
from sqlalchemy import select
from datetime import datetime
import re


async def reconcile_statement_with_invoices(db, owner_id: int, statement_id: int):
    """
    Matches StatementItems with invoices based on amount, vendor, date proximity.
    """

    from .models import StatementItem
    from ..invoices.models import Invoice

    stmt_items = (
        (
            await db.execute(
                select(StatementItem).where(StatementItem.statement_id == statement_id)
            )
        )
        .scalars()
        .all()
    )

    if not stmt_items:
        return

    invoices = (
        (await db.execute(select(Invoice).where(Invoice.owner_id == owner_id)))
        .scalars()
        .all()
    )

    if not invoices:
        return

    for item in stmt_items:
        try:
            tx_amount = float(re.sub(r"[^0-9.]", "", item.amount or "0"))
        except:
            continue

        best_invoice = None
        best_score = 0
        best_reason = ""

        for inv in invoices:

            if item.transaction_type == "debit" and inv.type != "expense":
                continue
            if item.transaction_type == "credit" and inv.type != "sales":
                continue

            try:
                inv_amount = float(re.sub(r"[^0-9.]", "", inv.total or "0"))
            except:
                continue

            if abs(tx_amount - inv_amount) > 1.00:
                continue

            amount_score = 100

            vendor_score = fuzz.partial_ratio(
                (item.description or "").lower(),
                (inv.vendor_name or "").lower(),
            )

            date_score = 0
            try:
                tx_date = datetime.strptime(item.transaction_date, "%d/%m/%Y")
                inv_date = None
                if inv.invoice_date:
                    inv_date = datetime.strptime(inv.invoice_date, "%d-%m-%Y")

                if inv_date:
                    days = abs((tx_date - inv_date).days)
                    if days <= 3:
                        date_score = 100
                    elif days <= 7:
                        date_score = 70
                    elif days <= 15:
                        date_score = 40
            except:
                pass

            total_score = amount_score * 0.6 + vendor_score * 0.3 + date_score * 0.1

            if total_score > best_score:
                best_score = total_score
                best_invoice = inv
                best_reason = f"amount match ({tx_amount}) + vendor {vendor_score}% + date_score {date_score}"

        if best_invoice and best_score >= 70:
            item.matched_invoice_id = best_invoice.id
            item.match_confidence = int(best_score)
            item.match_reason = best_reason
            item.is_matched = True
            print(f"Matched StatementItem {item.id} → Invoice {best_invoice.id}")

    await db.commit()
