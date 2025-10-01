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
    }

    for entity in doc.entities:
        etype = entity.type_
        val = entity.mention_text.strip() if entity.mention_text else None

        if etype == "supplier_name":
            fields["vendor_name"] = val
        elif etype == "invoice_id":
            fields["invoice_number"] = val
        elif etype == "invoice_date":
            fields["invoice_date"] = val
        elif etype in ("vat_tax_id", "tax_id", "registration_id"):
            fields["trn_vat_number"] = val
        elif etype == "subtotal":
            fields["before_tax_amount"] = val
        elif etype == "total_tax_amount":
            fields["tax_amount"] = val
        elif etype == "total_amount":
            fields["total"] = val

    return fields
