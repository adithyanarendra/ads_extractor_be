import os
import mimetypes
from dotenv import load_dotenv
from google.cloud import documentai
from typing import Dict, Optional
import re
from dateutil import parser as date_parser


import cv2
import numpy as np
import io
from PIL import Image

load_dotenv()

print("Loaded credentials from:", os.getenv("GOOGLE_APPLICATION_CREDENTIALS"))

PROJECT_ID = os.getenv("GCP_PROJECT_ID")
LOCATION = os.getenv("GCP_LOCATION")
PROCESSOR_ID = os.getenv("GCP_PROCESSOR_ID")

client = documentai.DocumentProcessorServiceClient()

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

TOTAL_KEYWORDS = [
    "total",
    "payable",
    "net total",
    "receivable",
    "owed",
    "amount due",
]

DATE_KEYWORDS = [
    "invoice date",
    "date",
    "bill date",
    "issue date",
]


MONTHS = {
    "jan": "01",
    "feb": "02",
    "mar": "03",
    "apr": "04",
    "may": "05",
    "jun": "06",
    "jul": "07",
    "aug": "08",
    "sep": "09",
    "sept": "09",
    "oct": "10",
    "nov": "11",
    "dec": "12",
}


def normalize_date(date_str: str) -> Optional[str]:
    """Convert any date string to DD-MM-YYYY format, handling multiple separators and month names."""
    if not date_str:
        return None
    try:
        s = date_str.lower().strip()
        # Replace month abbreviations with numbers
        for k, v in MONTHS.items():
            s = re.sub(rf"\b{k}\b", v, s)

        # Unify separators: ".", "/", " ", "_" → "-"
        s = re.sub(r"[./_]", "-", s)
        s = re.sub(r"\s+", "-", s)

        # Ensure 2-digit day/month parts
        parts = re.split(r"[-]", s)
        parts = [p.zfill(2) if p.isdigit() and len(p) == 1 else p for p in parts]
        s = "-".join(parts)

        dt = date_parser.parse(s, dayfirst=True, fuzzy=True)
        return dt.strftime("%d-%m-%Y")
    except Exception:
        return None


def clean_number(text: str) -> Optional[str]:
    """Keep only digits, dot, comma; remove spaces/currency symbols."""
    if not text:
        return None
    match = re.findall(r"[\d,.]+", text.replace(" ", ""))
    if match:
        return match[0].replace(",", "")
    return None


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


def extract_date_after_keyword(tokens, keywords, window=3) -> Optional[str]:
    """Look for date string after keywords and normalize it."""
    for i, t in enumerate(tokens):
        text = t["text"].lower()
        if any(kw in text for kw in keywords):
            for j in range(1, window + 1):
                if i + j >= len(tokens):
                    break
                next_text = tokens[i + j]["text"].strip()
                if next_text in [":", "#"]:
                    continue
                try_date = normalize_date(next_text)
                if try_date:
                    return try_date
    return None


def extract_any_date(tokens) -> Optional[str]:
    """Fallback: scan all tokens for standalone date-like patterns."""
    text = " ".join(t["text"] for t in tokens)

    # Common patterns (DD-MM-YYYY, DD.MM.YYYY, 21 Aug 2025, etc.)
    patterns = [
        r"\b\d{1,2}[-./\s]?\d{1,2}[-./\s]?\d{2,4}\b",
        r"\b\d{1,2}\s?(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s?\d{2,4}\b",
        r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s?\d{1,2},?\s?\d{2,4}\b",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            normalized = normalize_date(match.group(0))
            if normalized:
                return normalized
    return None


def extract_total_amount(tokens, keywords, window=3) -> Optional[str]:
    """Extract numeric value after total-related keywords."""
    for i, t in enumerate(tokens):
        text = t["text"].lower()
        if any(kw in text for kw in keywords):
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
                return clean_number("".join(collected))
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


# TO-DO deprecate this
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


def preprocess_image_bytes(file_bytes: bytes) -> bytes:
    """Enhance image quality for better OCR results."""
    # Convert bytes to numpy array
    nparr = np.frombuffer(file_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

    # Convert to grayscale
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Increase contrast using CLAHE
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    gray = clahe.apply(gray)

    # Optional: denoise
    gray = cv2.fastNlMeansDenoising(gray, None, 30, 7, 21)

    # Optional: thresholding
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    # Optional: deskew
    coords = np.column_stack(np.where(thresh > 0))
    angle = cv2.minAreaRect(coords)[-1]
    if angle < -45:
        angle = -(90 + angle)
    else:
        angle = -angle
    (h, w) = thresh.shape
    M = cv2.getRotationMatrix2D((w // 2, h // 2), angle, 1.0)
    rotated = cv2.warpAffine(
        thresh, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE
    )

    # Convert back to bytes
    is_success, buffer = cv2.imencode(".png", rotated)
    return buffer.tobytes()


def fix_tax_amount(fields: Dict[str, Optional[str]]) -> Dict[str, Optional[str]]:
    """
    Fix tax and before-tax amounts:
    - Only recalculate if tax is missing or invalid.
    - before_tax = total * 100 / 105
    - tax = total - before_tax
    - Keep existing tax if it is valid (within 0 and total).
    - Round to 2 decimals.
    """
    try:
        total = float(fields["total"]) if fields["total"] else None
        if not total:
            return fields

        tax = float(fields["tax_amount"]) if fields["tax_amount"] else None
        before_tax = (
            float(fields["before_tax_amount"]) if fields["before_tax_amount"] else None
        )

        if tax is None or tax < 0 or tax > total:
            before_tax = round(total * 100 / 105, 2)
            tax = round(total - before_tax, 2)

        elif before_tax is None:
            before_tax = round(total - tax, 2)

        fields["before_tax_amount"] = f"{before_tax:.2f}"
        fields["tax_amount"] = f"{tax:.2f}"

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
    # for page_index, page in enumerate(doc.pages):
    #     for token_index, token in enumerate(page.tokens):
    #         token_text = get_token_text(token, doc.text)
    #         confidence = token.layout.confidence if token.layout.confidence else 0.0
    #         tokens.append(
    #             {
    #                 "text": token_text,
    #                 "confidence": confidence,
    #                 "page": page_index + 1,
    #                 "token_index": token_index,
    #             }
    #         )
    #         fields["all_tokens"].append(
    #             {
    #                 "text": token_text,
    #                 "confidence": confidence,
    #                 "page": page_index + 1,
    #                 "token_index": token_index,
    #                 "bounding_box": (
    #                     [
    #                         {"x": round(v.x, 4), "y": round(v.y, 4)}
    #                         for v in token.layout.bounding_poly.vertices
    #                     ]
    #                     if token.layout.bounding_poly
    #                     and token.layout.bounding_poly.vertices
    #                     else None
    #                 ),
    #                 "block_id": getattr(token.layout, "id", None),
    #             }
    #         )

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
            fields["invoice_date"] = normalize_date(val)
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

    if not fields["invoice_date"]:
        # Try keyword-based detection
        date_str = extract_date_after_keyword(tokens, DATE_KEYWORDS)
        normalized = normalize_date(date_str)

        if not normalized:
            # Try full-document fallback
            normalized = extract_any_date(tokens)

        fields["invoice_date"] = normalized

    if not fields["total"]:
        fields["total"] = extract_total_amount(tokens, TOTAL_KEYWORDS)

    # Optional: If tax invoice, also keep tax/before-tax/TRN logic
    if contains_keyword(doc.text.lower(), TAX_INVOICE_KEYWORDS):
        if not fields["trn_vat_number"]:
            fields["trn_vat_number"] = extract_number_after_keyword(
                tokens, TRN_VAT_KEYWORDS
            )
        if not fields["before_tax_amount"]:
            fields["before_tax_amount"] = extract_number_after_keyword(
                tokens, BEFORE_TAX_KEYWORDS
            )
        if not fields["tax_amount"]:
            fields["tax_amount"] = extract_number_after_keyword(
                tokens, TAX_AMOUNT_KEYWORDS
            )

    # Derive before-tax if missing
    if fields["total"] and fields["tax_amount"] and not fields["before_tax_amount"]:
        try:
            fields["before_tax_amount"] = str(
                float(fields["total"]) - float(fields["tax_amount"])
            )
        except Exception:
            pass

    fields = fix_tax_amount(fields)

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
