from pydantic import BaseModel, EmailStr


class UserCreate(BaseModel):
    email: EmailStr
    password: str


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
