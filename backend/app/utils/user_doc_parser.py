import os, base64, mimetypes, json, re
from fastapi.concurrency import run_in_threadpool
from dateutil import parser as date_parser
from datetime import datetime
from openai import OpenAI
from sqlalchemy.future import select
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from ..api.user_docs.models import UserDocs

from .ocr_parser import convert_pdf_to_images
from .doc_prompts import get_prompt, ALLOWED_DOC_TYPES, GENERIC_TYPES
from .doc_fields import DOC_TYPE_MAP

from ..utils.r2 import upload_to_r2_bytes, delete_from_r2

DOC_TYPE_DETECT_PROMPT = """
You are a universal document classifier.

Given the images of a document, classify it into one of these doc_type values.
Choose the most accurate and specific option:

CORE UAE & GLOBAL ID DOCUMENTS:
- passport
- emirates_id
- driving_license
- residency_visa
- employee_visa

BUSINESS COMPLIANCE DOCUMENTS:
- vat_certificate
- ct_certificate
- trade_license
- moa  // memorandum of association
- company_profile
- board_resolution

VEHICLE & INSURANCE:
- car_insurance
- vehicle_registration
- vehicle_purchase_invoice

FINANCIAL DOCUMENTS:
- bank_statement
- salary_certificate
- tax_invoice
- payment_receipt

AGREEMENTS & LEGAL DOCUMENTS:
- rental_contract
- employment_contract
- contract_agreement
- noc_letter

OTHER:
- other_document

Rules:
- Choose ONLY one doc_type.
- If the document clearly matches a category (e.g., Indian Driving License), classify it as "driving_license".
- If unsure or unfamiliar, return: "other_document".

Return ONLY JSON:

{
  "doc_type": "driving_license"
}
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


def slugify(value: str | None) -> str:
    if not value:
        return ""
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    return value.strip("_")


def resolve_new_filename(doc, detected_doc_type, data):
    slug = slugify

    if detected_doc_type == "passport":
        return f"passport_{slug(data.get('passport_name')) or doc.user_id}"

    if detected_doc_type == "trade_license":
        return f"trade_license_{slug(data.get('tl_business_name_en')) or doc.user_id}"

    if detected_doc_type == "ct_certificate":
        suffix = (
            slug(data.get("ct_legal_name_en"))
            or slug(data.get("ct_trn"))
            or str(doc.user_id)
        )
        return f"ct_certificate_{suffix}"

    if detected_doc_type == "emirates_id":
        suffix = (
            slug(data.get("emirates_id_name"))
            or slug(data.get("emirates_id_number"))
            or doc.user_id
        )
        return f"emirates_id_{suffix}"

    if detected_doc_type == "vat_certificate":
        suffix = (
            slug(data.get("vat_legal_name_english"))
            or slug(data.get("vat_license_holder_name"))
            or doc.user_id
        )
        return f"vat_certificate_{suffix}"

    if detected_doc_type in GENERIC_TYPES:
        suffix = (
            slug(data.get("generic_document_number"))
            or slug(data.get("generic_title"))
            or doc.user_id
        )
        return f"{detected_doc_type}_{suffix}"

    return detected_doc_type


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
        images = await run_in_threadpool(convert_pdf_to_images, file_bytes)
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

            cls_res = await run_in_threadpool(
                client.responses.create,
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

    prompt = get_prompt(doc_type=detected_doc_type)

    chat_input = [{"type": "input_text", "text": prompt}]
    for mime, b64 in images:
        chat_input.append(
            {"type": "input_image", "image_url": f"data:{mime};base64,{b64}"}
        )

    try:
        res = await run_in_threadpool(
            client.responses.create,
            model="gpt-4.1",
            input=[{"role": "user", "content": chat_input}],
        )

        raw = res.output_text.strip()

        if "```" in raw:
            raw = re.sub(r"```(?:json)?|```", "", raw).strip()

        data = json.loads(raw)

        doc.generic_title = data.get("generic_title")
        doc.generic_document_number = data.get("generic_document_number")
        doc.generic_action_dates = data.get("generic_action_dates")
        doc.generic_parties = data.get("generic_parties")
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

        new_file_name = doc.file_name

        if detected_doc_type in ALLOWED_DOC_TYPES:
            if detected_doc_type == "passport":
                person_name = slugify(data.get("passport_name"))
                new_file_name = f"passport_{person_name or doc.user_id}"
            elif detected_doc_type == "trade_license":
                business = slugify(data.get("tl_business_name_en"))
                new_file_name = f"trade_license_{business or doc.user_id}"
            elif detected_doc_type == "ct_certificate":
                legal_en = slugify(data.get("ct_legal_name_en"))
                trn = slugify(data.get("ct_trn"))
                suffix = legal_en or trn or str(doc.user_id)
                new_file_name = f"ct_certificate_{suffix}"
            elif detected_doc_type == "emirates_id":
                person_name = slugify(data.get("emirates_id_name"))
                number = slugify(data.get("emirates_id_number"))
                suffix = person_name or number or str(doc.user_id)
                new_file_name = f"emirates_id_{suffix}"
            elif detected_doc_type == "vat_certificate":
                legal_en = slugify(data.get("vat_legal_name_english"))
                holder = slugify(data.get("vat_license_holder_name"))
                suffix = legal_en or holder or str(doc.user_id)
                new_file_name = f"vat_certificate_{suffix}"
            elif detected_doc_type in GENERIC_TYPES:
                ref = slugify(data.get("generic_document_number")) or slugify(
                    data.get("generic_title")
                )
                suffix = ref or str(doc.user_id)
                new_file_name = f"{detected_doc_type}_{suffix}"

            else:
                new_file_name = detected_doc_type

            doc.doc_type = detected_doc_type

        old_key = doc.file_url.split("r2.dev/")[-1]
        ext = "." + old_key.split(".")[-1]

        new_key = f"{doc.user_id}/{new_file_name}{ext}"

        new_url = await run_in_threadpool(upload_to_r2_bytes, file_bytes, new_key)

        try:
            await run_in_threadpool(delete_from_r2, old_key)
        except:
            print(f"[extract_document_meta] ⚠️ Failed to delete old R2 key: {old_key}")

        doc.file_name = new_file_name
        doc.file_url = new_url
        doc.is_processing = False

        await db.commit()
        await db.refresh(doc)
        print(f"[extract_document_meta] ✅ Metadata updated for doc {doc_id}")

    except Exception as e:
        print(f"[extract_document_meta] ❌ error {e}")
        await db.rollback()
