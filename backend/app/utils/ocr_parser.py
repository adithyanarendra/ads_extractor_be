import os
import mimetypes
from dotenv import load_dotenv
from google.cloud import documentai
from typing import Dict, Optional

load_dotenv()

print("Loaded credentials from:", os.getenv("GOOGLE_APPLICATION_CREDENTIALS"))

PROJECT_ID = os.getenv("GCP_PROJECT_ID")
LOCATION = os.getenv("GCP_LOCATION")
PROCESSOR_ID = os.getenv("GCP_PROCESSOR_ID")

TRN_VAT_KEYWORDS = [
    "trn number",
    "trn no",
    "trn",
    "tax registration number",
    "supplier tax registration number",
    "supplier tax id",
    "vat",
    "value added tax",
    "vat number",
    "vat no",
    "customer registration number",
    "customer registration no",
]

TAX_INVOICE_KEYWORDS = ["tax invoice"]


def contains_keyword(text: str, keywords: list) -> bool:
    text = text.lower()
    return any(kw in text for kw in keywords)


def get_token_text(token, full_text: str) -> str:
    """Extract token text from layout.text_anchor."""
    if not token.layout.text_anchor or not token.layout.text_anchor.text_segments:
        return ""
    segments = token.layout.text_anchor.text_segments
    text = ""
    for seg in segments:
        start = int(seg.start_index) if seg.start_index else 0
        end = int(seg.end_index) if seg.end_index else 0
        text += full_text[start:end]
    return text


def process_invoice(file_path: str) -> Dict[str, Optional[str]]:
    """Use Google Document AI to process invoice."""
    client = documentai.DocumentProcessorServiceClient()
    name = client.processor_path(PROJECT_ID, LOCATION, PROCESSOR_ID)

    mime_type, _ = mimetypes.guess_type(file_path)
    if mime_type not in [
        "application/pdf",
        "image/tiff",
        "image/gif",
        "image/jpeg",
        "image/png",
        "image/webp",
    ]:
        raise ValueError(f"Unsupported file type: {mime_type}")

    with open(file_path, "rb") as f:
        raw_document = documentai.RawDocument(content=f.read(), mime_type=mime_type)

    request = documentai.ProcessRequest(name=name, raw_document=raw_document)
    result = client.process_document(request=request)

    doc = result.document

    fields = {
        "vendor_name": None,
        "invoice_number": None,
        "invoice_date": None,
        "trn_vat_number": None,
        "before_tax_amount": None,
        "tax_amount": None,
        "total": None,
        "other_fields": {},
        "all_tokens": [],
    }

    for page_index, page in enumerate(doc.pages):
        for token_index, token in enumerate(page.tokens):
            token_text = get_token_text(token, doc.text)
            confidence = token.layout.confidence if token.layout.confidence else 0.0
            bounding_box = (
                [
                    {"x": vertex.x, "y": vertex.y}
                    for vertex in token.layout.bounding_poly.vertices
                ]
                if token.layout.bounding_poly
                else None
            )
            fields["all_tokens"].append(
                {
                    "text": token_text,
                    "confidence": confidence,
                    "page": page_index + 1,
                    "token_index": token_index,
                    "entity_type": getattr(token, "type_", None),
                    "bounding_box": bounding_box,
                }
            )

    is_tax_invoice = any(
        contains_keyword(entity.mention_text or "", TAX_INVOICE_KEYWORDS)
        for entity in doc.entities
    )

    # Process entities
    for entity in doc.entities:
        etype = entity.type_
        val = entity.mention_text.strip() if entity.mention_text else None
        val_lower = val.lower() if val else ""

        # TRN/VAT detection
        if etype in ("vat_tax_id", "tax_id", "registration_id"):
            fields["trn_vat_number"] = val
        elif val_lower and contains_keyword(val_lower, TRN_VAT_KEYWORDS):
            fields["trn_vat_number"] = val
        elif etype.lower() in [
            "supplier_tax_id",
            "supplier_taxnumber",
            "supplier_tax_number",
        ]:
            fields["trn_vat_number"] = val

        # Standard fields
        elif etype == "supplier_name":
            fields["vendor_name"] = val
        elif etype == "invoice_id":
            fields["invoice_number"] = val
        elif etype == "invoice_date":
            fields["invoice_date"] = val
        elif is_tax_invoice:
            if etype in ("subtotal", "amount_before_tax", "total_before_tax"):
                fields["before_tax_amount"] = val
            elif etype in ("total_tax_amount", "tax_amount"):
                fields["tax_amount"] = val
            elif etype in ("total_amount", "grand_total", "amount_due"):
                fields["total"] = val
        else:
            if etype in ("total_amount", "grand_total", "amount_due"):
                fields["total"] = val

        # Capture all other fields
        if etype not in [
            "supplier_name",
            "invoice_id",
            "invoice_date",
            "vat_tax_id",
            "tax_id",
            "registration_id",
            "subtotal",
            "amount_before_tax",
            "total_before_tax",
            "total_tax_amount",
            "tax_amount",
            "total_amount",
            "grand_total",
            "amount_due",
        ]:
            fields["other_fields"][etype] = val

    if is_tax_invoice and not fields["before_tax_amount"]:
        try:
            if fields["tax_amount"] and fields["total"]:
                before_tax = float(fields["total"].replace(",", "")) - float(
                    fields["tax_amount"].replace(",", "")
                )
                fields["before_tax_amount"] = str(before_tax)
            elif fields["total"]:
                fields["before_tax_amount"] = fields["total"]
        except Exception:
            pass

    return fields
