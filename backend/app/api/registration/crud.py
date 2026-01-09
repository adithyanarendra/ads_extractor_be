from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict
from app.api.registration import models
from app.utils.r2 import upload_to_r2_bytes
import uuid


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
    files: Dict[str, bytes],
):
    reg = await db.get(models.RegistrationUser, registration_id)
    if not reg:
        raise ValueError("Invalid registration id")

    if reg.status != models.RegistrationStatus.PENDING:
        raise ValueError("Documents already uploaded")

    for doc_key, file in files.items():
        filename = f"registration/{registration_id}/{doc_key}/{uuid.uuid4()}"
        url = upload_to_r2_bytes(file, filename)

        doc = models.RegistrationUserDoc(
            registration_user_id=registration_id,
            doc_key=doc_key,
            file_url=url,
        )
        db.add(doc)

    reg.status = models.RegistrationStatus.DOC_UPLOADED
    await db.commit()
