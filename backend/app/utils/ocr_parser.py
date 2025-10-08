import os
import mimetypes
from dotenv import load_dotenv
from google.cloud import documentai
from typing import Dict, Optional
import re

load_dotenv()

print("Loaded credentials from:", os.getenv("GOOGLE_APPLICATION_CREDENTIALS"))

PROJECT_ID = os.getenv("GCP_PROJECT_ID")
LOCATION = os.getenv("GCP_LOCATION")
PROCESSOR_ID = os.getenv("GCP_PROCESSOR_ID")

TRN_VAT_KEYWORDS = [
    "trn number",
    "trn no",
    "trn",
    "trn #",
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

BEFORE_TAX_KEYWORDS = [
    "subtotal",
    "amount before tax",
    "before tax",
    "net amount",
    "net total",
]

TAX_AMOUNT_KEYWORDS = ["tax", "vat", "gst", "tax amount", "vat amount", "gst amount"]


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


def clean_number(text: str) -> Optional[str]:
    """Keep only digits, dot, comma; remove spaces/currency symbols."""
    if not text:
        return None
    match = re.findall(r"[\d,.]+", text.replace(" ", ""))
    if match:
        return match[0].replace(",", "")
    return None


def extract_number_after_keyword(tokens, keywords, window=3):
    """Look for numeric value after keyword tokens."""
    for i, t in enumerate(tokens):
        text = t["text"].lower()
        if any(kw in text for kw in keywords):
            # Look next few tokens
            collected = []
            for j in range(1, window + 1):
                if i + j >= len(tokens):
                    break
                next_text = tokens[i + j]["text"].strip()
                if next_text in [":", "#"]:
                    continue
                if re.search(r"\d", next_text):
                    collected.append(next_text)
            if collected:
                # Join numbers in case TRN or amount is split into multiple tokens
                return clean_number("".join(collected))
    return None


client = documentai.DocumentProcessorServiceClient()


def process_invoice(file_path: str) -> Dict[str, Optional[str]]:
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

    result = client.process_document(
        request=documentai.ProcessRequest(name=name, raw_document=raw_document)
    )
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

    tokens = []
    for page_index, page in enumerate(doc.pages):
        for token_index, token in enumerate(page.tokens):
            token_text = get_token_text(token, doc.text)
            confidence = token.layout.confidence if token.layout.confidence else 0.0
            tokens.append(
                {
                    "text": token_text,
                    "confidence": confidence,
                    "page": page_index + 1,
                    "token_index": token_index,
                }
            )
            fields["all_tokens"].append({"text": token_text, "confidence": confidence})

    # --- Entity-based extraction ---
    for entity in doc.entities:
        etype = entity.type_
        val = entity.mention_text.strip() if entity.mention_text else None

        if etype in ("vat_tax_id", "tax_id", "registration_id"):
            fields["trn_vat_number"] = val
        elif etype == "supplier_name":
            fields["vendor_name"] = val
        elif etype == "invoice_id":
            fields["invoice_number"] = val
        elif etype == "invoice_date":
            fields["invoice_date"] = val
        elif etype in ("subtotal", "amount_before_tax", "total_before_tax"):
            fields["before_tax_amount"] = clean_number(val)
        elif etype in ("total_tax_amount", "tax_amount"):
            fields["tax_amount"] = clean_number(val)
        elif etype in ("total_amount", "grand_total", "amount_due"):
            fields["total"] = clean_number(val)
        else:
            if val:
                fields["other_fields"][etype] = val

    # --- Token-based fallback for better accuracy ---
    if not fields["trn_vat_number"]:
        fields["trn_vat_number"] = extract_number_after_keyword(
            tokens, TRN_VAT_KEYWORDS
        )

    if not fields["before_tax_amount"]:
        fields["before_tax_amount"] = extract_number_after_keyword(
            tokens, BEFORE_TAX_KEYWORDS
        )

    if not fields["tax_amount"]:
        fields["tax_amount"] = extract_number_after_keyword(tokens, TAX_AMOUNT_KEYWORDS)

    # Compute missing before_tax if total & tax are available
    if fields["total"] and fields["tax_amount"] and not fields["before_tax_amount"]:
        try:
            fields["before_tax_amount"] = str(
                float(fields["total"]) - float(fields["tax_amount"])
            )
        except Exception:
            pass

    return fields


def parse_document_fields(doc: documentai.Document) -> Dict[str, Optional[str]]:
    """Extract fields and tokens from the processed document."""
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

    tokens = []
    for page_index, page in enumerate(doc.pages):
        for token_index, token in enumerate(page.tokens):
            token_text = get_token_text(token, doc.text)
            confidence = token.layout.confidence if token.layout.confidence else 0.0
            tokens.append(
                {
                    "text": token_text,
                    "confidence": confidence,
                    "page": page_index + 1,
                    "token_index": token_index,
                }
            )
            fields["all_tokens"].append({"text": token_text, "confidence": confidence})

    # Entity-based extraction (Document AI structured fields)
    for entity in doc.entities:
        etype = entity.type_
        val = entity.mention_text.strip() if entity.mention_text else None

        if etype in ("vat_tax_id", "tax_id", "registration_id"):
            fields["trn_vat_number"] = val
        elif etype == "supplier_name":
            fields["vendor_name"] = val
        elif etype == "invoice_id":
            fields["invoice_number"] = val
        elif etype == "invoice_date":
            fields["invoice_date"] = val
        elif etype in ("subtotal", "amount_before_tax", "total_before_tax"):
            fields["before_tax_amount"] = clean_number(val)
        elif etype in ("total_tax_amount", "tax_amount"):
            fields["tax_amount"] = clean_number(val)
        elif etype in ("total_amount", "grand_total", "amount_due"):
            fields["total"] = clean_number(val)
        else:
            if val:
                fields["other_fields"][etype] = val

    # Fallback token-based extraction
    if not fields["trn_vat_number"]:
        fields["trn_vat_number"] = extract_number_after_keyword(
            tokens, TRN_VAT_KEYWORDS
        )

    if not fields["before_tax_amount"]:
        fields["before_tax_amount"] = extract_number_after_keyword(
            tokens, BEFORE_TAX_KEYWORDS
        )

    if not fields["tax_amount"]:
        fields["tax_amount"] = extract_number_after_keyword(tokens, TAX_AMOUNT_KEYWORDS)

    # Derive before-tax if missing
    if fields["total"] and fields["tax_amount"] and not fields["before_tax_amount"]:
        try:
            fields["before_tax_amount"] = str(
                float(fields["total"]) - float(fields["tax_amount"])
            )
        except Exception:
            pass

    return fields


def process_invoice_bytes(file_bytes: bytes, file_ext: str) -> Dict[str, Optional[str]]:
    """Run Document AI OCR on bytes (no file I/O)."""
    mime_type, _ = mimetypes.guess_type("dummy" + file_ext)
    if mime_type not in [
        "application/pdf",
        "image/tiff",
        "image/gif",
        "image/jpeg",
        "image/png",
        "image/webp",
    ]:
        raise ValueError(f"Unsupported file type: {mime_type}")

    name = client.processor_path(PROJECT_ID, LOCATION, PROCESSOR_ID)
    raw_doc = documentai.RawDocument(content=file_bytes, mime_type=mime_type)
    result = client.process_document(
        request=documentai.ProcessRequest(name=name, raw_document=raw_doc)
    )
    return parse_document_fields(result.document)
