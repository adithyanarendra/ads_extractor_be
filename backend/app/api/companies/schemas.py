from pydantic import BaseModel, EmailStr, ConfigDict
from typing import Optional, List
from datetime import datetime


class CompanyBase(BaseModel):
    name: str
    contact_person: Optional[str]
    email: Optional[EmailStr]
    number: Optional[str]
    address: Optional[str]
    users_allowed: Optional[List[str]] = []


class CompanyCreate(CompanyBase):
    pass


class CompanyUpdate(BaseModel):
    name: Optional[str]
    contact_person: Optional[str]
    email: Optional[EmailStr]
    number: Optional[str]
    address: Optional[str]
    users_allowed: Optional[List[str]]


class CompanyOut(CompanyBase):
    id: int
    created_by: Optional[str]
    created_at: Optional[datetime]
    last_updated_by: Optional[str]
    last_updated_date: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)
