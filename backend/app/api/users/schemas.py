from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime
from app.api.lov.currency import CurrencyEnum


class UserBase(BaseModel):
    id: int
    email: EmailStr
    name: Optional[str] = None
    is_admin: bool
    is_approved: bool
    is_accountant: bool
    is_qb_connected: bool 
    is_zb_connected: bool  
    created_at: datetime
    updated_at: datetime
    subscription_status: Optional[str] = None
    paid_till: Optional[datetime] = None
    skip_payment_check: Optional[bool] = None

    class Config:
        from_attributes = True

class UserOut(UserBase):
    pass
    

class UserCreate(BaseModel):
    email: EmailStr
    password: str
    name: Optional[str] = None


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str


class ChangeUserTypeRequest(BaseModel):
    is_admin: bool


class ResetPasswordRequest(BaseModel):
    email: EmailStr
    new_password: str


class UpdateUserRequest(BaseModel):
    user_id: Optional[int] = None
    name: Optional[str] = None
    is_accountant: Optional[bool] = None
    currency: Optional[CurrencyEnum] = None


class PaymentOverrideRequest(BaseModel):
    skip_payment_check: bool


class SelectCompanyPayload(BaseModel):
    company_id: int

class AccountingServiceRequest(BaseModel):
    """Schema for connecting or disconnecting an accounting service."""
    service: str
