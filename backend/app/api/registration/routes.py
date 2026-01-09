from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, Request
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

    reg = await crud.create_registration(db, registration_type, name, phone, confirmed)
    return reg


@router.post("/{registration_id}/documents")
async def upload_documents(
    registration_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    form = await request.form()
    files = {key: value for key, value in form.items() if hasattr(value, "filename")}

    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")

    file_bytes = {key: await value.read() for key, value in files.items()}

    try:
        await crud.upload_documents(db, registration_id, file_bytes)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"ok": True, "msg": "Documents uploaded successfully"}
