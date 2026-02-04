from pydantic import BaseModel, EmailStr
from typing import List
from datetime import datetime
from app.api.registration.models import RegistrationStatus, RegistrationType


class RegistrationDocOut(BaseModel):
    id: int
    doc_key: str
    file_url: str
    uploaded_at: datetime

    class Config:
        from_attributes = True


class RegistrationAdminOut(BaseModel):
    id: int
    name: str
    phone: str
    registration_type: RegistrationType
    status: RegistrationStatus
    created_at: datetime
    documents: List[RegistrationDocOut]

    class Config:
        from_attributes = True


class ApproveRegistrationRequest(BaseModel):
    name: str
    email: EmailStr
    password: str


class RejectRegistrationRequest(BaseModel):
    reason: str


class RegistrationDownloadFile(BaseModel):
    doc_id: int
    filename: str


class RegistrationDownloadRequest(BaseModel):
    files: List[RegistrationDownloadFile]
