import os
import base64
import mimetypes
from typing import Dict, Optional, Any, List, Tuple
from dotenv import load_dotenv
from openai import OpenAI
import json
from dateutil import parser as date_parser
from pdf2image import convert_from_bytes
from io import BytesIO
import re


load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY not found in environment")

client = OpenAI(api_key=OPENAI_API_KEY)


def normalize_date(date_str: str) -> str | None:
    """
    Convert any date string to DD-MM-YYYY format.
    Returns None if parsing fails.
    """
    if not date_str:
        return None
    try:
        dt = date_parser.parse(date_str, dayfirst=True)
        return dt.strftime("%d-%m-%Y")
    except Exception:
        return None


def clean_amount(value: Optional[str]) -> Optional[str]:
    """
    Removes currency symbols, codes, and extra text from amount strings.
    Example: "AED 1,234.50" -> "1234.50"
    """
    if not value:
        return None
    # Remove currency symbols and codes (common ones)
    value = re.sub(r"(?i)(aed|inr|usd|eur|gbp|rs|dhs|sar|₹|\$|€|£|¥)", "", value)
    # Remove all non-numeric characters except dot, comma, minus
    value = re.sub(r"[^0-9.,-]", "", value)
    # Clean up multiple commas (e.g., "1,234,56" -> "1234.56")
    value = value.replace(",", "")
    return value.strip() or None

def to_two_decimals(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    try:
        return f"{float(value):.2f}"
    except ValueError:
        return None


def convert_pdf_to_images(file_bytes: bytes) -> List[Tuple[str, str]]:
    """
    Converts a PDF file (bytes) to a list of (mime_type, base64_image) tuples.
    Each image is encoded as base64 PNG.
    """
    images_base64 = []
    try:
        images = convert_from_bytes(file_bytes, fmt="png", dpi=200)
        for img in images:
            buf = BytesIO()
            img.save(buf, format="PNG")
            b64_img = base64.b64encode(buf.getvalue()).decode("utf-8")
            images_base64.append(("image/png", b64_img))
        return images_base64
    except Exception as e:
        raise RuntimeError(f"Failed to convert PDF to images: {str(e)}")


def process_invoice(file_bytes: bytes, file_ext: str, doc_type: str = "expense") -> Dict[str, Any]:
    doc_type = (doc_type or "expense").lower()
    if doc_type not in ("expense", "sales"):
        doc_type = "expense"
    print(f"[ocr_parser] Processing invoice with type={doc_type}")
    result = {
        "vendor_name": None,
        "invoice_number": None,
        "invoice_date": None,
        "trn_vat_number": None,
        "before_tax_amount": None,
        "tax_amount": None,
        "total": None,
        "error": None,
        "other_text": None,
        "line_items": [],
        "description": None,
    }

    try:
        mime_type, _ = mimetypes.guess_type("dummy" + file_ext)
        images_base64 = []

        if mime_type == "application/pdf":
            images_base64 = convert_pdf_to_images(file_bytes)
        elif mime_type in [
            "image/jpeg",
            "image/png",
            "image/webp",
            "image/tiff",
            "image/gif",
        ]:
            images_base64 = [(mime_type, base64.b64encode(file_bytes).decode("utf-8"))]
        else:
            raise ValueError(f"Unsupported file type: {mime_type}")

        b64_image = base64.b64encode(file_bytes).decode("utf-8")

        if doc_type == "sales":
            role_note = """
IMPORTANT: This is a SALES invoice (we sold to a customer).
Whenever the instructions say "vendor" or "seller", TREAT THEM AS THE CUSTOMER.
Map CUSTOMER name to `vendor_name` and CUSTOMER TRN/VAT to `trn_vat_number`.
"""
        else:
            role_note = """
This is an EXPENSE invoice (a bill from supplier/vendor). Extract supplier/vendor details normally.
"""

        prompt = role_note + """
You are a highly precise AI specialized in **UAE tax invoices**. Your goal is to extract every important field **with maximum accuracy**. Time is not a concern — correctness is the top priority.

---

### ⚡ Key Rules

1. **Vendor TRN**
- Only extract the **seller/vendor TRN** (ignore buyer, recipient, or other TRNs).
- The TRN is always **exactly 15 digits**, **no dashes, no spaces**.
- Possible labels: "TRN", "TRN#", "TRN No", "TRN Number", "Tax Registration Number", "Supplier TRN", "Company TRN".
- If the TRN is unclear, return `null`. Do **not guess**.

2. **Invoice Numbers**
- `invoice_number`: the unique invoice identifier.
- It can contain text sometimes, make sure you capture that too.
- Possible labels: "Inv", "INV#", "Invoice", "Company Invoice Number", and so on.
- 🚨 **DO NOT EXTRACT** any of the following as invoice numbers. If a document only shows these, return `null`:
  - Folio No / Folio #
  - Room No / Room #
  - Reservation No / Reservation #
  - Confirmation No / Confirmation #
  - Guest No / Guest #
  - Check # / Receipt No
  - Order No / Booking No
- ✅ **ONLY** treat numbers as invoice numbers when the label clearly says "Invoice", "INV", or "Invoice No".
- **IMPORTANT for thermal/faded bills**: if the invoice number is faint, partially visible, or unclear, do your best to salvage the readable portion:
  - Extract any digits you CAN read, even if incomplete (e.g., "123" from "INV-1234").
  - Mark it as best-effort by prefixing with `~` (e.g., `~123` or `~INV-12`).
  - Only return `null` if absolutely no digits are visible—do **not** invent digits.
  - DO NOT guess digits you cannot see; capture only what IS readable.

3. **Invoice Date** 
- `invoice_date`: extract the date **directly from the image**, especially for handwritten invoices.
- Normalize to **DD-MM-YYYY**.
- Carefully interpret each digit in the day, month, and year; do not guess unclear digits.
- Cross-verify the year if possible using nearby context (e.g., invoice number, header, footer, or other printed text).
- Example: if the date reads "12-08-25" but the year contextually should be 2025, correct it to "12-08-2025".
- If the date is unclear or any digit is unreadable, return `null` instead of guessing.

4. **Amounts (Decimals Required)**
- **Always extract the numeric total as written on the invoice** first. Do not invent numbers. Example: if the invoice shows "1234.50", that is the `total`.
- `before_tax_amount`: extract from invoice if available; otherwise, calculate as `total * 100 / 105` **only to verify consistency**.
- `tax_amount`: extract from invoice if available; otherwise, calculate as `total - before_tax_amount` **only to verify consistency**.
- **Do not include commas or currency symbols**.
- If the numeric total is unclear or inconsistent, **look for the amount in words on the invoice** (e.g., "One thousand two hundred thirty-four dirhams and fifty fils") and convert it to numeric form. Use this as the primary `total` if it matches the context.
- If still unclear or inconsistent, mark the relevant field `null`.
- `currency`: AED, DHS, or the symbol seen.

5. **Line Items**
- Extract each line item EXACTLY as shown in the table.
- **CRITICAL**: Identify the correct columns. Common headers are:
  - Item Code/SKU/Product Code
  - Description/Item Name
  - Quantity/Qty
  - Unit Price/Rate (price per single item)
  - Amount/Subtotal/Line Total (quantity × unit price)
  - Tax (VAT/tax for this line)
  - Total (amount + tax)
- **DO NOT confuse the final total with unit price.**
- Each line item must include:
  {
    "description": string,
    "quantity": number,
    "unit_price": number (price for ONE unit),
    "amount": number (quantity × unit_price, before tax),
    "tax": number (optional),
    "line_total": number (optional, amount + tax)
  }
- If the table structure is unclear, return empty array instead of guessing.

Example:
If invoice shows: "STORAGE BOX | Qty: 15 | Unit Price: 19.04 | Subtotal: 285.57 | Tax: 14.28 | Total: 299.85"
Correct extraction:
{
  "description": "STORAGE BOX W/LID",
  "quantity": "15",
  "unit_price": "19.04",
  "amount": "285.57",
  "tax": "14.28",
  "line_total": "299.85"
}

6. **Description**
- Provide a concise 1–2 sentence human-readable summary of the invoice (vendor, date, total, and purpose if obvious). Do **not** invent facts.


7. **Other Text**
- Any extra text, notes, or remarks from the invoice.

---

### ✅ Verification & Confidence

- Double-check all fields internally.  
- Only return **fields you are confident in**.
- If any field seems inconsistent, unclear, or does not satisfy the amount relations, return `null` instead of guessing.

---

### 🔢 Output Format

Return **only one valid JSON object** exactly as below:

{
  "vendor_name": string | null,
  "invoice_number": string | null,
  "invoice_date": string | null,
  "trn_vat_number": string | null,
  "before_tax_amount": string | null,
  "tax_amount": string | null,
  "total": string | null,
  "description": string | null,
  "currency": string | null,
  "line_items": [
    {
      "description": string | null,
      "quantity": string | null,
      "unit_price": string | null,
      "amount": string | null
    }
  ],
  "other_text": string | null
}

- Do **not** include markdown, comments, explanations, or extra text.  
- Do **not** invent or guess digits.  
- Only output the JSON object.
- **All numeric fields must include decimals** even if zero (e.g., "1234.00").
"""

        gpt_input = [{"type": "input_text", "text": prompt}]
        for mime, b64_image in images_base64[:3]:
            gpt_input.append(
                {"type": "input_image", "image_url": f"data:{mime};base64,{b64_image}"}
            )

        response = client.responses.create(
            model="gpt-4.1",
            input=[{"role": "user", "content": gpt_input}],
        )

        # --- Extract text output ---
        output_text = response.output_text.strip() if response.output_text else ""
        print("\n--- RAW GPT RESPONSE START ---\n")
        print(output_text)
        print("\n--- RAW GPT RESPONSE END ---\n")

        if not output_text:
            result["error"] = "GPT returned empty response"
            return result

        # --- Strip code blocks if present ---
        if "```" in output_text:
            import re

            match = re.search(r"```(?:json)?(.*?)```", output_text, re.DOTALL)
            if match:
                output_text = match.group(1).strip()

        # --- Try parsing JSON ---
        try:
            fields = json.loads(output_text)
            for key in result.keys():
                if key in fields:
                    result[key] = fields[key]
            result["invoice_date"] = normalize_date(result.get("invoice_date"))
            result["before_tax_amount"] = to_two_decimals(
                clean_amount(result.get("before_tax_amount"))
            )
            result["tax_amount"] = to_two_decimals(clean_amount(result.get("tax_amount")))
            result["total"] = to_two_decimals(clean_amount(result.get("total")))
            inv_no = result.get("invoice_number")
            other_text = result.get("other_text") or ""
            if inv_no:
                lower_inv = str(inv_no).lower()
                if any(
                    key in lower_inv
                    for key in [
                        "folio",
                        "room",
                        "reservation",
                        "confirmation",
                        "guest",
                        "check",
                        "receipt",
                        "order",
                        "booking",
                    ]
                ):
                    result["invoice_number"] = None
                else:
                    pattern_parts = [
                        r"folio\\s*(?:no|number|#)?",
                        r"room\\s*(?:no|number|#)?",
                        r"reservation\\s*(?:no|number|#)?",
                        r"confirmation\\s*(?:no|number|#)?",
                        r"guest\\s*(?:no|number|#)?",
                        r"check\\s*(?:#|no|number)?",
                        r"receipt\\s*(?:no|number|#)?",
                        r"order\\s*(?:no|number|#)?",
                        r"booking\\s*(?:no|number|#)?",
                    ]
                    inv_pattern = re.escape(str(inv_no))
                    if re.search(
                        rf"(?:{'|'.join(pattern_parts)})\\s*[:\\-]?\\s*{inv_pattern}",
                        other_text,
                        re.IGNORECASE,
                    ):
                        result["invoice_number"] = None

        except json.JSONDecodeError as e:
            result["error"] = f"Failed to parse GPT response: {str(e)}"
            result["other_text"] = output_text  # Preserve raw for debugging

    except Exception as e:
        result["error"] = str(e)

    return result
