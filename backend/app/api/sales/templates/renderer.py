import os
from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML, CSS

BASE_DIR = os.path.dirname(__file__)
env = Environment(loader=FileSystemLoader(BASE_DIR))


def load_template(name):
    return env.get_template(name)


async def render_simple_invoice_pdf(invoice):
    template = load_template("simple.html")
    html_content = template.render(invoice=invoice)
    pdf = HTML(string=html_content).write_pdf()
    return pdf


async def render_detailed_invoice_pdf(invoice):
    template = load_template("detailed.html")
    html_content = template.render(invoice=invoice)
    pdf = HTML(string=html_content).write_pdf()
    return pdf


async def render_thermal_invoice_pdf(invoice, width_mm=58):
    template = load_template("thermal.html")

    html_content = template.render(invoice=invoice, width_mm=width_mm)

    pdf = HTML(string=html_content).write_pdf(
        stylesheets=[CSS(string=f"@page {{ size: {width_mm}mm auto; margin: 2mm; }}")]
    )

    return pdf
