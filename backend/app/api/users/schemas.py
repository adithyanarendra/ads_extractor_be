from pydantic import BaseModel, EmailStr
from typing import Optional


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
    email: str
    new_password: str


class UpdateUserRequest(BaseModel):
    user_id: Optional[int] = None
    name: Optional[str] = None
    is_accountant: Optional[bool] = None


class SelectCompanyPayload(BaseModel):
    company_id: int
