from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, Request
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict
from app.core.database import get_db
from app.api.registration import crud, schemas, models

router = APIRouter(prefix="/registration", tags=["registration"])


@router.post("", response_model=schemas.RegistrationOut)
async def create_registration(
    registration_type: models.RegistrationType = Form(...),
    name: str = Form(...),
    phone: str = Form(...),
    confirmed: bool = Form(...),
    db: AsyncSession = Depends(get_db),
):
    if not confirmed:
        raise HTTPException(status_code=400, detail="Confirmation required")

    clean_name = name.strip()
    clean_phone = phone.strip()
    existing = await db.scalar(
        select(models.RegistrationUser).where(
            models.RegistrationUser.registration_type == registration_type,
            models.RegistrationUser.name == clean_name,
            models.RegistrationUser.phone == clean_phone,
            models.RegistrationUser.status != models.RegistrationStatus.REJECTED,
        )
    )
    if existing:
        return schemas.RegistrationOut(
            id=existing.id, status=existing.status, exists=True
        )

    reg = await crud.create_registration(
        db, registration_type, clean_name, clean_phone, confirmed
    )
    return schemas.RegistrationOut(id=reg.id, status=reg.status, exists=False)


@router.post("/{registration_id}/documents")
async def upload_documents(
    registration_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    form = await request.form()
    files = {}
    for key, value in form.multi_items():
        if not hasattr(value, "filename"):
            continue
        files.setdefault(key, []).append(value)

    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")

    file_data = {}
    for key, items in files.items():
        entries = []
        for item in items:
            entries.append((await item.read(), item.filename or ""))
        file_data[key] = entries

    try:
        docs = await crud.upload_documents(db, registration_id, file_data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "ok": True,
        "msg": "Documents uploaded successfully",
        "docs": docs,
    }


@router.get("/{registration_id}/documents")
async def list_documents(
    registration_id: int,
    db: AsyncSession = Depends(get_db),
):
    reg = await db.get(models.RegistrationUser, registration_id)
    if not reg:
        raise HTTPException(status_code=404, detail="Registration not found")

    result = await db.execute(
        select(models.RegistrationUserDoc).where(
            models.RegistrationUserDoc.registration_user_id == registration_id
        )
    )
    docs = result.scalars().all()
    return {
        "ok": True,
        "docs": [
            {"id": d.id, "doc_key": d.doc_key, "file_url": d.file_url}
            for d in docs
        ],
    }


@router.post("/{registration_id}/submit-for-review", response_model=schemas.RegistrationOut)
async def submit_for_review(
    registration_id: int,
    db: AsyncSession = Depends(get_db),
):
    reg = await db.get(models.RegistrationUser, registration_id)
    if not reg:
        raise HTTPException(status_code=404, detail="Registration not found")

    if reg.status == models.RegistrationStatus.REJECTED:
        raise HTTPException(status_code=400, detail="Registration is rejected")
    if reg.status == models.RegistrationStatus.APPROVED:
        raise HTTPException(status_code=400, detail="Registration is already approved")

    doc_count = await db.scalar(
        select(func.count(models.RegistrationUserDoc.id)).where(
            models.RegistrationUserDoc.registration_user_id == registration_id
        )
    )
    if not doc_count:
        raise HTTPException(status_code=400, detail="No documents uploaded")

    if reg.status == models.RegistrationStatus.PENDING:
        reg.status = models.RegistrationStatus.DOC_UPLOADED
        await db.commit()
        await db.refresh(reg)

    return reg
