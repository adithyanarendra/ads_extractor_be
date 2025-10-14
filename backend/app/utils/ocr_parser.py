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


def process_invoice(file_bytes: bytes, file_ext: str) -> Dict[str, Any]:
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

        prompt = """
You are an AI trained to extract invoice fields. Extract the following strictly as JSON:
{
  "vendor_name": string | null,
  "invoice_number": string | null,
  "invoice_date": string | null,
  "trn_vat_number": string | null,
  "before_tax_amount": string | null,
  "tax_amount": string | null,
  "total": string | null,
  "other_text": string | null,
  "line_items": array
}
Return ONLY valid JSON. No markdown, no explanations, no comments.
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
            result["before_tax_amount"] = clean_amount(result.get("before_tax_amount"))
            result["tax_amount"] = clean_amount(result.get("tax_amount"))
            result["total"] = clean_amount(result.get("total"))

        except json.JSONDecodeError as e:
            result["error"] = f"Failed to parse GPT response: {str(e)}"
            result["other_text"] = output_text  # Preserve raw for debugging

    except Exception as e:
        result["error"] = str(e)

    return result
