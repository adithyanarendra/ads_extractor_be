from datetime import datetime, timedelta
from collections import Counter
import re

def sanitize_total(value):
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)

    clean = re.sub(r"[^0-9.]", "", str(value))
    try:
        return float(clean) if clean else 0.0
    except ValueError:
        return 0.0
    
def compute_sales_analytics(invoices):
    total_sales = 0.0
    sales_count = 0
    customers = set()
    customer_totals = Counter()
    amount_receivable = 0.0

    seen = set()  # to remove duplicates

    for inv in invoices:
        if not inv.invoice_date:
            continue

        # Deduplicate
        key = (inv.invoice_number, inv.invoice_date)
        if key in seen:
            continue
        seen.add(key)

        amount = sanitize_total(inv.total)

        # Skip zero-value invoices
        if amount <= 0:
            continue

        total_sales += amount
        sales_count += 1

        if inv.vendor_name:
            customers.add(inv.vendor_name)
            customer_totals[inv.vendor_name] += amount

        if inv.is_paid is False:
            amount_receivable += amount

    top_customer = customer_totals.most_common(1)

    return {
        "sales_count": sales_count,
        "total_sales": round(total_sales, 2),
        "customers_count": len(customers),
        "amount_receivable": round(amount_receivable, 2),
        "top_customer": {
            "name": top_customer[0][0] if top_customer else None,
            "amount": round(top_customer[0][1], 2) if top_customer else 0.0,
        },
    }
