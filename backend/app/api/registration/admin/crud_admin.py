import io
import asyncio
import zipfile
import mimetypes
from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.utils.r2 import get_file_from_r2
from app.api.registration import models
from app.api.users import crud as users_crud
from app.api.user_docs import crud as user_docs_crud


async def list_registrations_with_docs(db: AsyncSession):
    result = await db.execute(
        select(models.RegistrationUser)
        .where(models.RegistrationUser.status != models.RegistrationStatus.REJECTED)
        .order_by(models.RegistrationUser.created_at.desc())
    )
    regs = result.scalars().all()

    out = []
    for r in regs:
        docs_result = await db.execute(
            select(models.RegistrationUserDoc).where(
                models.RegistrationUserDoc.registration_user_id == r.id
            )
        )
        docs = docs_result.scalars().all()
        r.documents = docs
        out.append(r)

    return out


async def approve_registration(
    db: AsyncSession,
    registration_id: int,
    name: str,
    email: str,
    password: str,
    approved_by: int,
    certificate_file: UploadFile | None = None,
):
    reg = await db.get(models.RegistrationUser, registration_id)
    if not reg:
        raise ValueError("Registration not found")

    if reg.status != models.RegistrationStatus.DOC_UPLOADED:
        raise ValueError("Documents not uploaded")

    user = await users_crud.create_user(
        db=db,
        email=email,
        password=password,
        name=name,
        created_by=approved_by,
    )

    docs_result = await db.execute(
        select(models.RegistrationUserDoc).where(
            models.RegistrationUserDoc.registration_user_id == registration_id
        )
    )
    docs = docs_result.scalars().all()

    for doc in docs:
        if not doc.file_url:
            continue
        key = doc.file_url.split("r2.dev/")[-1]
        file_obj = await asyncio.to_thread(get_file_from_r2, key)
        if not file_obj:
            continue
        file_bytes = file_obj.read()
        ext = mimetypes.guess_extension(
            mimetypes.guess_type(doc.file_url)[0] or ""
        ) or ""
        filename = f"{doc.doc_key}{ext}"
        upload_file = UploadFile(
            filename=filename,
            file=io.BytesIO(file_bytes),
        )
        result = await user_docs_crud.upload_user_doc(
            db=db,
            user_id=user.id,
            doc_type="auto",
            file_bytes=file_bytes,
            file=upload_file,
        )
        if result.get("ok"):
            try:
                asyncio.create_task(
                    user_docs_crud.process_doc_metadata(
                        result["data"]["id"], file_bytes, "auto"
                    )
                )
            except Exception:
                pass

    if certificate_file:
        file_bytes = await certificate_file.read()
        certificate_file.file.seek(0)
        doc_type = (
            "ct_certificate"
            if reg.registration_type == models.RegistrationType.CT
            else "vat_certificate"
        )
        result = await user_docs_crud.upload_user_doc(
            db=db,
            user_id=user.id,
            doc_type=doc_type,
            file_bytes=file_bytes,
            file=certificate_file,
        )
        if result.get("ok"):
            try:
                asyncio.create_task(
                    user_docs_crud.process_doc_metadata(
                        result["data"]["id"], file_bytes, doc_type
                    )
                )
            except Exception:
                pass

    reg.status = models.RegistrationStatus.APPROVED
    await db.commit()

    return user


async def reject_registration(
    db: AsyncSession,
    registration_id: int,
    reason: str,
    rejected_by: int,
):
    reg = await db.get(models.RegistrationUser, registration_id)
    if not reg:
        raise ValueError("Registration not found")

    if reg.status == models.RegistrationStatus.APPROVED:
        raise ValueError("Approved registration cannot be rejected")

    reg.status = models.RegistrationStatus.REJECTED
    reg.reject_reason = reason

    await db.commit()


async def generate_registration_docs_zip(
    db: AsyncSession,
    registration_id: int,
    files: list[dict],
) -> tuple[io.BytesIO, str]:
    reg = await db.get(models.RegistrationUser, registration_id)
    if not reg:
        raise ValueError("Registration not found")

    doc_ids = [f.get("doc_id") for f in files if f.get("doc_id")]
    if not doc_ids:
        raise ValueError("No documents selected")

    docs_result = await db.execute(
        select(models.RegistrationUserDoc).where(
            models.RegistrationUserDoc.registration_user_id == registration_id,
            models.RegistrationUserDoc.id.in_(doc_ids),
        )
    )
    docs = docs_result.scalars().all()
    docs_by_id = {doc.id: doc for doc in docs}

    file_tasks = []
    zipped_files = []

    def _get_ext_from_url(url: str) -> str:
        if not url:
            return ""
        try:
            filename = url.split("?")[0].split("/")[-1]
            if "." in filename:
                return filename.rsplit(".", 1)[1].lower()
        except Exception:
            return ""
        return ""

    for entry in files:
        doc_id = entry.get("doc_id")
        filename = entry.get("filename")
        doc = docs_by_id.get(doc_id)
        if not doc or not doc.file_url or not filename:
            continue
        if "." not in filename:
            ext = _get_ext_from_url(doc.file_url)
            if ext:
                filename = f"{filename}.{ext}"
        key = doc.file_url.split("r2.dev/")[-1]
        file_tasks.append(
            (
                filename,
                asyncio.create_task(_fetch_file_bytes(key)),
            )
        )

    if not file_tasks:
        raise ValueError("No valid documents found")

    for (filename, task), content in zip(
        file_tasks, await asyncio.gather(*[task for _, task in file_tasks])
    ):
        if not content:
            continue
        zipped_files.append({"filename": filename, "content": content})

    if not zipped_files:
        raise ValueError("No document files available for download")

    zip_buffer = io.BytesIO()
    folder_name = f"{reg.name} Registration Docs"
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for file in zipped_files:
            zip_file.writestr(f"{folder_name}/{file['filename']}", file["content"])

    zip_buffer.seek(0)
    return zip_buffer, folder_name


async def _fetch_file_bytes(filename: str):
    file_obj = await asyncio.to_thread(get_file_from_r2, filename)
    if not file_obj:
        return None
    return file_obj.read()
