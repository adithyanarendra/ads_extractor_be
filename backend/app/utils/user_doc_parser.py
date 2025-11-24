import os, base64, mimetypes, json, re
from dateutil import parser as date_parser
from datetime import datetime
from openai import OpenAI
from sqlalchemy.future import select
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from ..api.user_docs.models import UserDocs

from .ocr_parser import convert_pdf_to_images
from .doc_prompts import get_prompt, ALLOWED_DOC_TYPES
from .doc_fields import DOC_TYPE_MAP

DOC_TYPE_DETECT_PROMPT = f"""
You are a document classifier for UAE compliance documents.

Given the following images of ONE document, decide which type it is.
You MUST choose exactly ONE of these values:

{", ".join(sorted(ALLOWED_DOC_TYPES))}

Definitions (for your reasoning only, do NOT output them):
- "vat_certificate": UAE VAT registration certificates.
- "ct_certificate": UAE Corporate Tax registration certificates.
- "trade_license": Trade/Business license documents.
- "passport": Passport identity page.
- "emirates_id": UAE Emirates ID card.
- "moa": Memorandum of Association or similar company formation documents.

Return ONLY a JSON object like:

{{
  "doc_type": "vat_certificate"
}}

Rules:
- "doc_type" must be exactly one of the allowed values.
- If unsure, choose the closest matching type.
- No extra keys, no comments, no markdown.
"""


OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY)


def normalize_date(date_str: str):
    if not date_str:
        return None
    try:
        dt = date_parser.parse(date_str, dayfirst=True)
        return dt
    except:
        return None


def parse_date(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(value)
    except:
        # handle other formats if API returns differently
        try:
            return datetime.strptime(value, "%Y-%m-%d")
        except:
            return None


async def extract_document_meta(
    db: AsyncSession, doc_id: int, file_bytes: bytes, doc_type: str
):
    """
    Extract only expiry date + filing date + batch start + address
    """
    result = await db.execute(select(UserDocs).where(UserDocs.id == doc_id))
    doc = result.scalar_one_or_none()

    if not doc:
        print(f"[extract_document_meta] Doc not found: {doc_id}")
        return

    filename = doc.file_url.lower()
    ext = filename.split(".")[-1]
    is_pdf = ext == "pdf"

    if is_pdf:
        images = convert_pdf_to_images(file_bytes)
    else:
        mime, _ = mimetypes.guess_type(f"a.{ext}")
        images = [(mime, base64.b64encode(file_bytes).decode())]

    detected_doc_type = doc_type
    if doc_type == "auto":
        try:
            classify_input = [{"type": "input_text", "text": DOC_TYPE_DETECT_PROMPT}]
            for mime, b64 in images:
                classify_input.append(
                    {"type": "input_image", "image_url": f"data:{mime};base64,{b64}"}
                )

            cls_res = client.responses.create(
                model="gpt-4.1",
                input=[{"role": "user", "content": classify_input}],
            )

            raw_cls = cls_res.output_text.strip()
            if "```" in raw_cls:
                raw_cls = re.sub(r"```(?:json)?|```", "", raw_cls).strip()

            cls_data = json.loads(raw_cls)
            candidate = cls_data.get("doc_type")

            if candidate in ALLOWED_DOC_TYPES:
                detected_doc_type = candidate
            else:
                print(
                    f"[extract_document_meta] ⚠️ Invalid detected doc_type={candidate}, falling back to default prompt"
                )
        except Exception as e:
            print(f"[extract_document_meta] ❌ classification error {e}")
            detected_doc_type = doc_type

    if detected_doc_type in ALLOWED_DOC_TYPES:
        await db.execute(
            delete(UserDocs).where(
                UserDocs.user_id == doc.user_id,
                UserDocs.file_name == detected_doc_type,
                UserDocs.id != doc_id,
            )
        )
        await db.commit()

    prompt = get_prompt(doc_type=detected_doc_type)

    chat_input = [{"type": "input_text", "text": prompt}]
    for mime, b64 in images:
        chat_input.append(
            {"type": "input_image", "image_url": f"data:{mime};base64,{b64}"}
        )

    try:
        res = client.responses.create(
            model="gpt-4.1", input=[{"role": "user", "content": chat_input}]
        )

        raw = res.output_text.strip()

        if "```" in raw:
            raw = re.sub(r"```(?:json)?|```", "", raw).strip()

        data = json.loads(raw)

        doc.expiry_date = normalize_date(data.get("expiry_date")) or doc.expiry_date
        doc.filing_date = normalize_date(data.get("filing_date"))
        doc.batch_start_date = normalize_date(data.get("batch_start_date"))
        doc.company_address = data.get("company_address")

        allowed_fields = DOC_TYPE_MAP.get(detected_doc_type, [])

        for field in allowed_fields:
            value = data.get(field)
            if value is not None:
                # Handle date-like fields safely
                if any(s in field for s in ["date", "period", "since", "expiry"]):
                    setattr(doc, field, normalize_date(value))
                else:
                    setattr(doc, field, value)

        if detected_doc_type in ALLOWED_DOC_TYPES:
            doc.file_name = detected_doc_type

        await db.commit()
        await db.refresh(doc)
        print(f"[extract_document_meta] ✅ Metadata updated for doc {doc_id}")

    except Exception as e:
        print(f"[extract_document_meta] ❌ error {e}")
        await db.rollback()
