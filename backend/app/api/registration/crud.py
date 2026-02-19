from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func
from sqlalchemy import select
from typing import Dict, Tuple, List
from app.api.registration import models
from app.utils.r2 import upload_to_r2_bytes, delete_from_r2
import uuid
import os


async def create_registration(
    db: AsyncSession,
    registration_type: models.RegistrationType,
    name: str,
    phone: str,
    confirmed: bool,
) -> models.RegistrationUser:
    reg = models.RegistrationUser(
        registration_type=registration_type,
        name=name,
        phone=phone,
        confirmed=confirmed,
    )
    db.add(reg)
    await db.commit()
    await db.refresh(reg)
    return reg


async def upload_documents(
    db: AsyncSession,
    registration_id: int,
    files: Dict[str, List[Tuple[bytes, str]]],
) -> List[Dict[str, str]]:
    reg = await db.get(models.RegistrationUser, registration_id)
    if not reg:
        raise ValueError("Invalid registration id")

    if reg.status in (
        models.RegistrationStatus.APPROVED,
        models.RegistrationStatus.REJECTED,
    ):
        raise ValueError("Registration is not editable")

    created_docs = []
    for doc_key, file_entries in files.items():
        for file_bytes, original_name in file_entries:
            _, ext = os.path.splitext(original_name or "")
            safe_ext = ext.lower() if ext else ""
            filename = (
                f"registration/{registration_id}/{doc_key}/{uuid.uuid4()}{safe_ext}"
            )
            url = upload_to_r2_bytes(file_bytes, filename)

            doc = models.RegistrationUserDoc(
                registration_user_id=registration_id,
                doc_key=doc_key,
                file_url=url,
            )
            db.add(doc)
            await db.flush()
            created_docs.append(
                {"id": doc.id, "doc_key": doc.doc_key, "file_url": doc.file_url}
            )

    if reg.status == models.RegistrationStatus.PENDING:
        reg.status = models.RegistrationStatus.DOC_UPLOADED
    await db.commit()
    return created_docs
