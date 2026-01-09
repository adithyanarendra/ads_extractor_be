from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.api.registration import models
from app.api.users import crud as users_crud


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
