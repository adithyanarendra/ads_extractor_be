import os
from re import findall
import asyncio
from calendar import month_abbr
from datetime import datetime, timezone
from dateutil import parser as date_parser
from fastapi import UploadFile, HTTPException, status
from fastapi.responses import StreamingResponse
from fastapi.concurrency import run_in_threadpool
import mimetypes
from sqlalchemy.future import select
from sqlalchemy import delete, or_
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List

from ...core.database import SessionLocal
from .models import UserDocs
from ..sales.models import SellerProfile
from ..users.crud import get_user_by_id
from ..batches import crud as batches_crud
from ...utils.r2 import upload_to_r2_bytes, get_file_from_r2, delete_from_r2
from ...utils.user_doc_parser import extract_document_meta

from ...utils.doc_prompts import ALLOWED_DOC_TYPES, GENERIC_TYPES
from ...utils import doc_fields as fields

from .schemas import DOC_SCHEMA_MAP, BaseDocSchema

MONTH_MAP = {m.lower(): i for i, m in enumerate(month_abbr) if m}
SELLER_DOC_TYPES = {"vat_certificate", "ct_certificate", "trade_license"}


def _seller_profile_fields_from_doc(doc: UserDocs):
    if doc.doc_type == "vat_certificate":
        company_name_en = doc.vat_legal_name_english or doc.legal_name or ""
        company_name_ar = doc.vat_legal_name_arabic
        company_address = doc.vat_registered_address or doc.company_address
        company_trn = doc.vat_tax_registration_number or ""
    elif doc.doc_type == "ct_certificate":
        company_name_en = doc.ct_legal_name_en or doc.legal_name or ""
        company_name_ar = doc.ct_legal_name_ar
        company_address = doc.ct_registered_address or doc.company_address
        company_trn = doc.ct_trn or ""
    elif doc.doc_type == "trade_license":
        company_name_en = doc.tl_business_name_en or doc.legal_name or ""
        company_name_ar = doc.tl_business_name_ar
        company_address = doc.company_address
        company_trn = doc.tl_registration_number or ""
    else:
        company_name_en = doc.legal_name or ""
        company_name_ar = None
        company_address = doc.company_address
        company_trn = ""

    vat_registered = bool(company_trn and company_trn.strip())

    return {
        "company_name_en": company_name_en,
        "company_name_ar": company_name_ar,
        "company_address": company_address,
        "company_trn": company_trn,
        "vat_registered": vat_registered,
    }


async def _get_seller_profile_by_user(db: AsyncSession, user_id: int):
    result = await db.execute(
        select(SellerProfile).where(SellerProfile.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def get_or_create_seller_profile(db: AsyncSession, user_id: int):
    profile = await _get_seller_profile_by_user(db, user_id)
    # Do not auto-create a profile from a single doc; require explicit selection/save.
    return profile


async def set_seller_profile(db: AsyncSession, user_id: int, doc_id: int):
    result = await db.execute(
        select(UserDocs).where(
            UserDocs.user_id == user_id,
            UserDocs.id == doc_id,
            UserDocs.doc_type.in_(SELLER_DOC_TYPES),
            UserDocs.is_processing == False,
        )
    )
    doc = result.scalar_one_or_none()
    if not doc:
        return {"ok": False, "error": "Document not found or not eligible"}

    fields = _seller_profile_fields_from_doc(doc)

    profile = await _get_seller_profile_by_user(db, user_id)
    if profile:
        profile.doc_id = doc.id
        profile.doc_type = doc.doc_type
        profile.company_name_en = fields["company_name_en"]
        profile.company_name_ar = fields["company_name_ar"]
        profile.company_address = fields["company_address"]
        profile.company_trn = fields["company_trn"]
        profile.vat_registered = fields["vat_registered"]
    else:
        profile = SellerProfile(
            user_id=user_id,
            doc_id=doc.id,
            doc_type=doc.doc_type,
            **fields,
        )
        db.add(profile)

    await db.commit()
    await db.refresh(profile)
    return {"ok": True, "data": profile}

def _allowed_update_keys_for_doc_type(doc_type: str):
    core_keys = {
        "file_name",
        "doc_type",
        "expiry_date",
        "filing_date",
        "batch_start_date",
        "generic_title",
        "generic_document_number",
        "generic_action_dates",
        "generic_parties",
    }

    allowed = set(core_keys)

    if doc_type == "vat_certificate":
        allowed.update(fields.VAT_FIELDS)
    elif doc_type == "ct_certificate":
        allowed.update(fields.CT_FIELDS)
    elif doc_type == "trade_license":
        allowed.update(fields.TL_FIELDS)
    elif doc_type == "passport":
        allowed.update(fields.PASSPORT_FIELDS)
    elif doc_type == "emirates_id":
        allowed.update(fields.EMIRATES_ID_FIELDS)
    elif doc_type in GENERIC_TYPES:
        # generic fields already included
        pass
    else:
        # if doc_type is None or other, still allow core + generic
        pass

    return allowed


async def update_user_doc(db: AsyncSession, user_id: int, doc_id: int, payload: dict):
    result = await db.execute(
        select(UserDocs).where(UserDocs.id == doc_id, UserDocs.user_id == user_id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        return {"ok": False, "error": "Document not found", "message": "Update failed"}

    target_doc_type = payload.get("doc_type") or doc.doc_type

    if payload.get("doc_type"):
        allowed_types = set(ALLOWED_DOC_TYPES) | set(GENERIC_TYPES)
        if payload["doc_type"] not in allowed_types:
            return {
                "ok": False,
                "error": "Invalid doc_type",
                "message": "Invalid doc_type provided",
            }

    allowed_keys = _allowed_update_keys_for_doc_type(target_doc_type)

    applied = {}
    for k, v in payload.items():
        if k not in allowed_keys:
            continue
        setattr(doc, k, v)
        applied[k] = v

    try:
        await db.commit()
        await db.refresh(doc)
        return {
            "ok": True,
            "message": "Document updated",
            "data": {"id": doc.id, "applied": applied},
        }
    except Exception as e:
        await db.rollback()
        return {"ok": False, "error": str(e), "message": "Update failed"}


async def upload_user_doc(
    db: AsyncSession,
    user_id: int,
    doc_type: str,
    file_bytes: bytes,
    file: UploadFile,
    expiry_date: Optional[str] = None,
):
    user = await get_user_by_id(db, user_id)
    if not user:
        return {"ok": False, "error": "User not found", "message": "Upload failed"}

    ext = os.path.splitext(file.filename)[1].lower()

    if not ext:
        if file.content_type == "application/pdf":
            ext = ".pdf"
        elif file.content_type in ["image/jpeg", "image/jpg"]:
            ext = ".jpg"
        elif file.content_type == "image/png":
            ext = ".png"
        else:
            import mimetypes

            ext = mimetypes.guess_extension(file.content_type) or ".pdf"

    timestamp = int(datetime.now(timezone.utc).timestamp())
    filename_with_ext = f"{doc_type}_{timestamp}{ext}"
    r2_key = f"{user_id}/{filename_with_ext}"

    file_url = upload_to_r2_bytes(file_bytes, r2_key)

    original_name = os.path.splitext(file.filename)[0] or filename_with_ext

    new_doc = UserDocs(
        user_id=user_id,
        file_name=original_name,
        file_url=file_url,
        expiry_date=expiry_date,
        doc_type=None,
        is_processing=True,
    )
    db.add(new_doc)
    await db.commit()
    await db.refresh(new_doc)

    return {
        "ok": True,
        "data": {
            "id": new_doc.id,
            "file_url": new_doc.file_url,
            "expiry_date": expiry_date,
        },
    }


async def list_user_docs(db: AsyncSession, user_id: int) -> List[UserDocs]:
    try:
        result = await db.execute(
            select(UserDocs).where(
                UserDocs.user_id == user_id,
                or_(UserDocs.doc_type != "sales_invoice_logo", UserDocs.doc_type.is_(None)),
            )
        )
        docs = result.scalars().all()
        data = [
            {
                "id": d.id,
                "file_name": d.file_name,
                "doc_type": d.doc_type,
                "file_url": d.file_url,
                "expiry_date": d.expiry_date,
                "uploaded_at": d.uploaded_at,
                "is_processing": d.is_processing,
            }
            for d in docs
        ]
        return {"ok": True, "message": "Documents retrieved successfully", "data": data}
    except Exception as e:
        return {"ok": False, "error": str(e), "message": "Failed to fetch documents"}


async def get_user_doc(db: AsyncSession, user_id: int, doc_id: int):
    result = await db.execute(
        select(UserDocs).where(UserDocs.user_id == user_id, UserDocs.id == doc_id)
    )
    doc = result.scalar_one_or_none()

    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Extract key from stored URL
    if "r2.dev/" in doc.file_url:
        filename = doc.file_url.split("r2.dev/")[-1]
    else:
        # if you're storing plain keys, adjust accordingly
        filename = doc.file_url

    file_stream = get_file_from_r2(filename)

    if not file_stream:
        raise HTTPException(status_code=404, detail="File missing from R2")

    import mimetypes

    mime_type, _ = mimetypes.guess_type(filename)
    if not mime_type:
        mime_type = "application/octet-stream"

    headers = {
        "Content-Disposition": f'inline; filename="{os.path.basename(filename)}"'
    }

    return StreamingResponse(file_stream, media_type=mime_type, headers=headers)


async def delete_user_doc(db: AsyncSession, user_id: int, doc_id: int):
    try:
        result = await db.execute(
            select(UserDocs).where(UserDocs.user_id == user_id, UserDocs.id == doc_id)
        )
        doc = result.scalar_one_or_none()

        if not doc:
            return {
                "ok": False,
                "error": "Document not found",
                "message": "Delete failed",
            }

        profile = await _get_seller_profile_by_user(db, user_id)
        if profile and profile.doc_id == doc_id:
            return {
                "ok": False,
                "error": "Document is used in Seller Profile",
                "message": "Cannot delete a Seller Profile document",
            }

        await db.execute(
            delete(UserDocs).where(
                UserDocs.user_id == user_id,
                UserDocs.id == doc_id,
            )
        )
        await db.commit()
        return {"ok": True, "message": f"Document {doc_id} deleted successfully"}
    except Exception as e:
        await db.rollback()
        return {"ok": False, "error": str(e), "message": "Delete failed"}


async def process_documents_info(db: AsyncSession, doc: UserDocs):
    if doc.doc_type == "sales_invoice_logo":
        return
    file_key = doc.file_url.split("r2.dev/")[-1]
    file_bytes = get_file_from_r2(file_key).read()

    ext = "." + file_key.split(".")[-1]

    data = await run_in_threadpool(extract_document_meta, file_bytes, ext)
    if not data:
        return

    doc.expiry_date = data.get("expiry_date") or doc.expiry_date
    doc.filing_date = data.get("filing_date")
    doc.batch_start_date = data.get("batch_start_date")
    doc.company_address = data.get("company_address")

    await db.commit()
    await db.refresh(doc)


async def process_doc_metadata(doc_id: int, file_bytes: bytes, doc_type: str):
    if doc_type == "sales_invoice_logo":
        return
    if not file_bytes or len(file_bytes) < 100:
        print(f"[WARN] Empty or invalid file_bytes for doc {doc_id}")
        return

    async with SessionLocal() as db:
        await extract_document_meta(db, doc_id, file_bytes, doc_type)

        result = await db.execute(select(UserDocs).where(UserDocs.id == doc_id))
        doc = result.scalar_one_or_none()
        if not doc:
            return

        if doc.doc_type == "vat_certificate":
            await _autocreate_vat_batches_for_doc(db, doc)


async def get_user_doc_details(db: AsyncSession, user_id: int, doc_id: int):
    result = await db.execute(
        select(UserDocs).where(UserDocs.user_id == user_id, UserDocs.id == doc_id)
    )
    doc = result.scalar_one_or_none()

    if not doc:
        return {
            "ok": False,
            "error": "Document not found",
            "message": "No document found",
        }

    doc_type = doc.doc_type
    Schema = DOC_SCHEMA_MAP.get(doc_type, BaseDocSchema)

    return {
        "ok": True,
        "message": "Document metadata retrieved successfully",
        "data": Schema.from_orm(doc).dict(),
    }

def get_fy_aware_year(month_name: str) -> int:
    now = datetime.now(timezone.utc)
    fy_start_year = now.year if now.month >= 4 else now.year - 1

    month_num = MONTH_MAP.get(month_name[:3].lower())
    if not month_num:
        return fy_start_year

    return fy_start_year + 1 if month_num <= 3 else fy_start_year

def transform_vat_name_to_current_fy(original_name: str) -> str:
    months = findall(r"[A-Za-z]{3,}", original_name)
    if len(months) < 2:
        return original_name

    start_month, end_month = months[0], months[1]
    end_year = get_fy_aware_year(end_month)

    return f"{start_month} - {end_month} {end_year}"

async def _autocreate_vat_batches_for_doc(db: AsyncSession, doc: UserDocs):
    owner_id = doc.user_id

    period_names = [
        doc.vat_batch_one,
        doc.vat_batch_two,
        doc.vat_batch_three,
        doc.vat_batch_four,
    ]

    for raw_name in period_names:
        if not raw_name:
            continue

        name = transform_vat_name_to_current_fy(raw_name)

        year_match = findall(r"\b(20\d{2})\b", name)
        batch_year = int(year_match[0]) if year_match else None

        res = await batches_crud.create_batch(
            db,
            name=name,
            owner_id=owner_id,
            invoice_ids=None,
            batch_year=batch_year,
        )

        if res.get("ok"):
            parent_id = res["data"]["id"]
            asyncio.create_task(
                _autocreate_child_batches(owner_id, name, parent_id)
            )


async def _autocreate_child_batches(
    owner_id: int, parent_name: str, parent_id: Optional[int] = None
):
    async with SessionLocal() as db:
        parsed = batches_crud.parse_batch_range(parent_name)
        if not parsed:
            print(f"[child-batches] Skipping invalid range: {parent_name}")
            return

        start_month, end_month, start_year, end_year = parsed

        current_year = start_year
        month = start_month

        while True:
            month_name = month_abbr[month]
            child_name = f"{month_name} {current_year}"

            try:
                await batches_crud.create_batch(
                    db,
                    name=child_name,
                    owner_id=owner_id,
                    invoice_ids=None,
                    batch_year=current_year,
                    parent_id=parent_id,
                )
                print(
                    f"[child-batches] ✅ Created child batch: {child_name} (parent={parent_id})"
                )
            except Exception as e:
                print(f"[child-batches] ⚠️ Skipped child {child_name}: {e}")

            if current_year == end_year and month == end_month:
                break

            month += 1
            if month > 12:
                month = 1
                current_year += 1


async def get_user_docs_for_timeline(db: AsyncSession, user_id: int):
    result = await db.execute(
        select(UserDocs).where(
            UserDocs.user_id == user_id, UserDocs.doc_type != "sales_invoice_logo"
        )
    )
    docs = result.scalars().all()

    timeline = []
    now = datetime.now(timezone.utc)

    def _parse_action_date(value):
        if not value:
            return None
        if isinstance(value, datetime):
            parsed = value
        else:
            try:
                parsed = date_parser.parse(str(value), dayfirst=True)
            except Exception:
                return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed

    def _roll_forward_yearly(dt, now_dt):
        if not dt:
            return None
        rolled = dt
        while rolled < now_dt:
            try:
                rolled = rolled.replace(year=rolled.year + 1)
            except ValueError:
                rolled = rolled.replace(month=2, day=28, year=rolled.year + 1)
        return rolled

    for d in docs:
        action_candidates = [
            d.filing_date,
            d.vat_vat_return_due_date,
            d.ct_first_return_due_date,
        ]

        if isinstance(d.generic_action_dates, list):
            action_candidates.extend(d.generic_action_dates)

        action_dates = [
            dt for dt in (_parse_action_date(v) for v in action_candidates) if dt
        ]
        future_actions = [dt for dt in action_dates if dt >= now]
        action_date = min(future_actions) if future_actions else None
        if not action_date and action_dates and d.doc_type in {
            "vat_certificate",
            "ct_certificate",
        }:
            latest_past = max(action_dates)
            action_date = _roll_forward_yearly(latest_past, now)

        expiry = None
        if d.doc_type not in {"vat_certificate", "ct_certificate"}:
            expiry = _parse_action_date(
                d.expiry_date
                or d.tl_expiry_date
                or d.passport_expiry_date
                or d.emirates_id_expiry_date
            )

        effective_date = action_date or expiry
        days_left = (effective_date - now).days if effective_date else None

        timeline.append(
            {
                "id": d.id,
                "file_name": d.file_name,
                "doc_type": d.doc_type,
                "action_date": action_date,
                "action_type": "action" if action_date else ("expiry" if expiry else None),
                "expiry_date": expiry,
                "days_left": days_left,
            }
        )

    timeline_sorted = sorted(
        timeline,
        key=lambda x: (
            x["days_left"] is None,
            x["days_left"] if x["days_left"] is not None else 999999,
        ),
    )

    return {
        "ok": True,
        "message": "Timeline sorted successfully",
        "data": timeline_sorted,
    }


async def get_sales_logo(db: AsyncSession, user_id: int):
    res = await db.execute(
        select(UserDocs).where(
            UserDocs.user_id == user_id, UserDocs.doc_type == "sales_invoice_logo"
        )
    )
    return res.scalar_one_or_none()


async def upload_sales_logo(db: AsyncSession, user_id: int, file: UploadFile):
    allowed = ["image/png", "image/jpeg", "image/jpg", "image/webp"]
    if file.content_type not in allowed:
        return {"ok": False, "message": "Invalid image type"}

    file_bytes = await file.read()

    existing = await get_sales_logo(db, user_id)
    if existing:
        try:
            key = existing.file_url.split("r2.dev/")[-1]
            delete_from_r2(key)
        except:
            pass
        await db.delete(existing)
        await db.commit()

    ext = ".png"
    r2_key = f"{user_id}/sales-invoice-logo-{user_id}{ext}"

    url = upload_to_r2_bytes(file_bytes, r2_key)

    new_doc = UserDocs(
        user_id=user_id,
        doc_type="sales_invoice_logo",
        file_name=f"sales-invoice-logo-{user_id}",
        file_url=url,
        expiry_date=None,
    )
    db.add(new_doc)
    await db.commit()
    await db.refresh(new_doc)

    return {"ok": True, "data": url}


async def get_processing_count(db: AsyncSession, user_id: int):
    result = await db.execute(
        select(UserDocs).where(
            UserDocs.user_id == user_id, UserDocs.is_processing == True
        )
    )
    docs = result.scalars().all()
    return len(docs)
