import os
import base64
import mimetypes
import json
import re
from typing import Dict, Any, List
from dateutil import parser as date_parser
from pdf2image import convert_from_bytes
from io import BytesIO
from PIL import Image
import pytesseract
import requests

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "qwen2.5vl:3b"
TIMEOUT = 180

def normalize_date(date_str: str) -> str | None:
    """Convert any date string to DD-MM-YYYY format."""
    if not date_str:
        return None
    try:
        dt = date_parser.parse(date_str, dayfirst=True)
        return dt.strftime("%d-%m-%Y")
    except Exception:
        return None


def clean_amount(value: str | None) -> str | None:
    """Clean up currency symbols, text, and non-numeric characters."""
    if not value:
        return None
    value = re.sub(r"(?i)(aed|inr|usd|eur|gbp|rs|dhs|sar|₹|\$|€|£|¥)", "", value)
    value = re.sub(r"[^0-9.,-]", "", value)
    value = value.replace(",", "")
    return value.strip() or None


def ocr_text(image: Image.Image):
    """Perform OCR and return structured text data."""
    return pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)


def extract_top_bottom_text(ocr_dict):
    """Split OCR text roughly into top/bottom halves based on y-coordinates."""
    if not ocr_dict["text"]:
        return "", ""

    h = max(ocr_dict["top"]) + max(ocr_dict["height"])
    mid = h / 2
    top_lines, bottom_lines = [], []

    for txt, top in zip(ocr_dict["text"], ocr_dict["top"]):
        if not txt.strip():
            continue
        (top_lines if top < mid else bottom_lines).append(txt)

    return " ".join(top_lines), " ".join(bottom_lines)


def find_all_trns(text: str) -> List[str]:
    """Find all TRN-like numbers starting with 100."""
    pattern = re.compile(r"100[\s\-]*([\d]{12})")
    matches = pattern.findall(text.replace("\n", " "))
    trns = []
    for m in matches:
        digits = "100" + m
        formatted = f"{digits[:3]}-{digits[3:7]}-{digits[7:11]}-{digits[11:]}"
        trns.append(formatted)
    return trns


def convert_pdf_to_image(file_bytes: bytes) -> Image.Image:
    """Convert a PDF (bytes) to first page image."""
    pages = convert_from_bytes(file_bytes, dpi=200)
    return pages[0]

def process_with_qwen(file_bytes: bytes, file_ext: str) -> Dict[str, Any]:
    
    result = {
        "vendor_name": None,
        "invoice_number": None,
        "invoice_date": None,
        "trn_vat_number": None,
        "before_tax_amount": None,
        "tax_amount": None,
        "total": None
        
    }

    try:
        mime_type, _ = mimetypes.guess_type("dummy" + file_ext)
        if not mime_type:
            raise ValueError("Could not detect file type")

        if mime_type == "application/pdf":
            img = convert_pdf_to_image(file_bytes)
        elif mime_type.startswith("image/"):
            img = Image.open(BytesIO(file_bytes))
        else:
            raise ValueError(f"Unsupported file type: {mime_type}")

        ocr_dict = ocr_text(img)
        top_text, bottom_text = extract_top_bottom_text(ocr_dict)

        top_trns = find_all_trns(top_text)
        bottom_trns = find_all_trns(bottom_text)
        vendor_trn_hint = top_trns[0] if top_trns else None

        buf = BytesIO()
        img.save(buf, format="PNG")
        b64_img = base64.b64encode(buf.getvalue()).decode("utf-8")

        fields = {
            "vendor_name": None,
            "invoice_number": None,
            "invoice_date": None,
            "trn_vat_number": None,
            "before_tax_amount": None,
            "tax_amount": None,
            "total": None
        }

        prompt = f"""
You are analyzing a UAE VAT invoice image and must extract vendor-related details only.

OCR summary (top half = vendor section, bottom half = customer section):

---TOP HALF (vendor section)---
{top_text[:2000]}

---BOTTOM HALF (customer section)---
{bottom_text[:2000]}

### TASK OBJECTIVE
Extract the **vendor’s details** only. Ignore all information related to customers, buyers, or bill-to parties.

### TRN Extraction Rules
1. A UAE VAT TRN always starts with "100" and has 15 digits (e.g., 1004-8324-6000-03).
2. If multiple TRNs are detected, the **first valid TRN in the top half** is the **vendor TRN** — this must always be used.
3. Never take TRNs appearing near or below words like “Customer”, “Buyer”, “Bill To”, “Recipient”, “Ship To”, etc.
4. If the same TRN appears in both halves, use the one in the **top half**.
5. Before finalizing, cross-check that the selected TRN visually belongs to the **vendor box/section** — not near any customer label.
6. If no valid TRN is found in the top half, output `"trn_vat_number": null`.

### Layout Understanding
Use invoice design cues to determine field ownership:
- If two labels (e.g., “Invoice No.” and “Date”) appear next to each other in a single line or box, pair them correctly with their values.
- Identify grouping boxes visually: vendor details (top left/right), invoice meta details (top right), customer section (bottom half).
- If multiple dates are found, prefer the one labeled “Invoice Date” or near “Invoice No.” and above the table of items.

### Verification and Sanity Checks
Before finalizing:
- Confirm that **invoice number**, **date**, and **TRN** belong to the same section (vendor metadata area).
- Cross-check extracted totals (before tax, tax amount, total) — they must be consistent and numeric.
- Ensure all numeric fields are strings and do not include currency symbols.

### OUTPUT FORMAT
Extract and return only the following JSON structure — no markdown, no text outside braces:

{json.dumps(fields, indent=2)}

### RULES
- Always output strictly valid JSON.
- Never include markdown formatting (like ```json).
- Never include explanations or reasoning text.
- Verify all extracted values twice before finalizing.
- If uncertain about a field, return it as null (not guessed).

Output only valid JSON.
"""


        resp = requests.post(
            OLLAMA_URL,
            json={
                "model": MODEL_NAME,
                "prompt": prompt,
                "images": [b64_img],
                "stream": False,
            },
            timeout=TIMEOUT,
        )

        if resp.status_code != 200:
            result["error"] = f"Ollama {resp.status_code}: {resp.text}"
            return result

        raw = resp.json().get("response", "").strip()

        print("\n--- RAW QWEN RESPONSE START ---\n")
        print(raw)
        print("\n--- RAW QWEN RESPONSE END ---\n")

        if raw.startswith("```"):
            raw = raw.strip("`").replace("json", "").strip("`")

        try:
            data = json.loads(raw)
        except Exception:
            result["error"] = "Failed to parse JSON output"
            result["other_text"] = raw
            return result

        if not data.get("trn_vat_number") and vendor_trn_hint:
            data["trn_vat_number"] = vendor_trn_hint
            data["trn_source"] = "regex_top_half"
        elif data.get("trn_vat_number") in bottom_trns and vendor_trn_hint:
            data["trn_vat_number"] = vendor_trn_hint
            data["trn_source"] = "corrected_vendor_trn"

        data["invoice_date"] = normalize_date(data.get("invoice_date"))
        data["before_tax_amount"] = clean_amount(data.get("before_tax_amount"))
        data["tax_amount"] = clean_amount(data.get("tax_amount"))
        data["total"] = clean_amount(data.get("total"))

        result.update(data)

    except Exception as e:
        result["error"] = str(e)

    return result

if __name__ == "__main__":
    with open("sample_invoice.pdf", "rb") as f:
        file_bytes = f.read()
    output = process_with_qwen(file_bytes, ".pdf")
    print(json.dumps(output, indent=2, ensure_ascii=False))
