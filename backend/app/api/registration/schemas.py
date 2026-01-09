from pydantic import BaseModel
from typing import Dict
from app.api.registration.models import RegistrationType, RegistrationStatus


class RegistrationCreate(BaseModel):
    registration_type: RegistrationType
    name: str
    phone: str
    confirmed: bool


class RegistrationOut(BaseModel):
    id: int
    status: RegistrationStatus

    class Config:
        from_attributes = True
