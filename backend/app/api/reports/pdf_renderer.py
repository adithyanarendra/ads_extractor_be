import os
from typing import Any, Dict

from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML

BASE_DIR = os.path.dirname(__file__)
TEMPLATE_DIR = os.path.join(BASE_DIR, "templates")

env = Environment(loader=FileSystemLoader(TEMPLATE_DIR))


def _render_template(template_name: str, data: Dict[str, Any]) -> bytes:
    template = env.get_template(template_name)
    html_content = template.render(report=data)
    return HTML(string=html_content).write_pdf()


def render_vat_report_pdf(data: Dict[str, Any]) -> bytes:
    return _render_template("vat_report.html", data)


def render_pnl_report_pdf(data: Dict[str, Any]) -> bytes:
    return _render_template("pnl_report.html", data)
