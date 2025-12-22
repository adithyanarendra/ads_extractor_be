import os
from ..crud import number_to_words
from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML, CSS

BASE_DIR = os.path.dirname(__file__)
env = Environment(loader=FileSystemLoader(BASE_DIR))


def load_template(name):
    return env.get_template(name)


async def render_simple_invoice_pdf(invoice, db):
    from ...user_docs.crud import get_sales_logo

    template = load_template("simple.html")

    settings_logo = await get_sales_logo(db, invoice.owner_id)
    logo_url = settings_logo.file_url if settings_logo else None

    html_content = template.render(
        invoice=invoice,
        logo_url=logo_url,
        total_in_words=number_to_words(invoice.total),
    )
    pdf = HTML(string=html_content).write_pdf()
    return pdf


async def render_detailed_invoice_pdf(invoice):
    template = load_template("detailed.html")
    html_content = template.render(
        invoice=invoice, total_in_words=number_to_words(invoice.total)
    )

    pdf = HTML(string=html_content).write_pdf()
    return pdf


async def render_thermal_invoice_pdf(invoice, width_mm=58):
    template = load_template("thermal_pdf.html")

    html_content = template.render(invoice=invoice, width_mm=width_mm)

    pdf = HTML(string=html_content).write_pdf(
        stylesheets=[CSS(string=f"@page {{ size: {width_mm}mm auto; margin: 2mm; }}")]
    )

    return pdf


async def render_thermal_invoice_html(invoice):
    template = load_template("thermal_print.html")

    html_content = template.render(invoice=invoice)

    return html_content
