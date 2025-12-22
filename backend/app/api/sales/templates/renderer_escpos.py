from escpos.printer import Dummy

LINE_WIDTH = 48  # 80mm
LEFT_COL = 30
RIGHT_COL = LINE_WIDTH - LEFT_COL
SEP = "─" * LINE_WIDTH


def wrap_text(text, width):
    if not text:
        return []
    words = text.split()
    lines = []
    line = ""

    for word in words:
        if len(line) + len(word) + 1 <= width:
            line = f"{line} {word}".strip()
        else:
            lines.append(line)
            line = word

    if line:
        lines.append(line)

    return lines


def render_invoice_escpos(invoice):
    p = Dummy()

    # ---- TITLE ----
    p.set(align="center", bold=True, width=2, height=2)
    p.text("TAX INVOICE\n")

    # ---- COMPANY ----
    p.set(align="center", bold=True, width=1, height=1)
    p.text(invoice.company_name + "\n")

    p.set(bold=False)

    if invoice.company_trn:
        p.text(f"TRN: {invoice.company_trn}\n")

    if invoice.company_address:
        for line in wrap_text(invoice.company_address, LINE_WIDTH):
            p.text(line + "\n")

    p.text("\n" + SEP + "\n")

    # ---- META ----
    p.set(align="left")
    p.text(f"Invoice No : {invoice.invoice_number}\n")
    p.text(f"Date       : {invoice.invoice_date.strftime('%d-%m-%Y')}\n")
    p.text("Currency   : AED\n")
    p.text(SEP + "\n")

    # ---- ITEMS HEADER ----
    p.set(bold=True)
    p.text(f"{'Item':<{LEFT_COL}}{'Amount':>{RIGHT_COL}}\n")
    p.set(bold=False)
    p.text(SEP + "\n")

    # ---- ITEMS ----
    for li in invoice.line_items:
        name = li.name or (li.product.name if li.product else "")
        desc = li.description or ""

        full_name = f"{name} - {desc}" if desc else name

        wrapped_name = wrap_text(full_name, LEFT_COL)

        # First line with amount
        p.text(f"{wrapped_name[0]:<{LEFT_COL}}{li.line_total:>{RIGHT_COL}.2f}\n")

        # Remaining wrapped lines (no amount)
        for extra in wrapped_name[1:]:
            p.text(f"{extra:<{LEFT_COL}}\n")

        # Quantity line
        qty_line = f"{li.quantity} x {li.unit_cost:.2f}"
        p.text(f"{qty_line:<{LEFT_COL}}\n")

    p.text(SEP + "\n")

    # ---- TOTALS ----
    def total_row(label, value, bold=False):
        p.set(bold=bold)
        p.text(f"{label:<{LEFT_COL}}{value:>{RIGHT_COL}.2f}\n")
        p.set(bold=False)

    total_row("Subtotal", invoice.subtotal)
    total_row("VAT", invoice.total_vat)

    if invoice.discount:
        total_row("Discount", -invoice.discount)

    p.text(SEP + "\n")
    total_row("TOTAL (AED)", invoice.total, bold=True)

    p.text(SEP + "\n")

    # ---- FOOTER ----
    p.set(align="center")
    p.text("This is a computer generated tax invoice\n")
    p.text("--AIcountant--\n")
    p.text("Thank you for your business\n")

    p.text("\n\n")
    p.cut()

    return bytes(p.output)
