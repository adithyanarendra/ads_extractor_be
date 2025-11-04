import os, base64, mimetypes, json, re
from dateutil import parser as date_parser
from datetime import datetime
from openai import OpenAI
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..api.user_docs.models import UserDocs

from .ocr_parser import convert_pdf_to_images
from .doc_prompts import get_prompt
from .doc_fields import DOC_TYPE_MAP


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

    prompt = get_prompt(doc_type=doc_type)

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

        allowed_fields = DOC_TYPE_MAP.get(doc_type, [])

        for field in allowed_fields:
            value = data.get(field)
            if value is not None:
                # Handle date-like fields safely
                if any(s in field for s in ["date", "period", "since", "expiry"]):
                    setattr(doc, field, normalize_date(value))
                else:
                    setattr(doc, field, value)

        await db.commit()
        await db.refresh(doc)
        print(f"[extract_document_meta] ✅ Metadata updated for doc {doc_id}")

    except Exception as e:
        print(f"[extract_document_meta] ❌ error {e}")
        await db.rollback()
