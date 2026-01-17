from datetime import datetime, timedelta
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import HTTPException, Depends
from fastapi.security import OAuth2PasswordBearer

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from .database import get_db
from app.api.organisations.models import Organisation
from app.api.users import models as user_models
from app.api.users import crud as users_crud
from app.core.roles import UserRole


SECRET_KEY = "SUPER_SECRET_KEY_CHANGE_ME"  # change for production
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/users/login")

def require_roles(*allowed_roles: UserRole):
    def _role_dependency(user: user_models.User = Depends(get_current_user)):
        try:
            role = UserRole(user.role)
        except ValueError:
            raise HTTPException(status_code=403, detail="Access denied")

        if role not in allowed_roles:
            raise HTTPException(status_code=403, detail="Access denied")

        return user

    return _role_dependency


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (
        expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return {"ok": True, "payload": payload}
    except JWTError:
        return {"ok": False, "error": "Invalid token"}


async def get_current_user(
    db: AsyncSession = Depends(get_db), token: str = Depends(oauth2_scheme)
) -> user_models.User:

    decoded = decode_token(token)
    if not decoded.get("ok"):
        raise HTTPException(status_code=401, detail=decoded.get("error"))

    payload = decoded["payload"]

    email = payload.get("sub")
    if not email:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    user = await users_crud.get_user_by_email(db, email)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="User account inactive")

    if not user.organisation_id:
        raise HTTPException(status_code=403, detail="Organisation missing")

    organisation = await db.get(Organisation, user.organisation_id)
    if not organisation or not organisation.is_active:
        raise HTTPException(status_code=403, detail="Organisation inactive")

    user.organisation = organisation

    user.jwt_is_super_admin = payload.get("is_admin", False)
    user.jwt_is_accountant = payload.get("is_accountant", False)
    user.jwt_company_id = payload.get("company_id")
    user.jwt_company_role = payload.get("company_role")
    user.jwt_acting_user_id = payload.get("acting_user_id")

    acting_id = payload.get("acting_user_id")
    if acting_id:
        user.effective_user_id = acting_id
    else:
        user.effective_user_id = user.id

    return user


async def get_current_user_from_token(token: str, db: AsyncSession):
    decoded = decode_token(token)
    if not decoded.get("ok"):
        raise HTTPException(status_code=401, detail="Invalid token")

    payload = decoded["payload"]

    email = payload.get("sub")
    if not email:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    result = await db.execute(
        select(user_models.User).where(user_models.User.email == email)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    user.jwt_is_super_admin = payload.get("is_admin", False)
    user.jwt_is_accountant = payload.get("is_accountant", False)
    user.jwt_company_id = payload.get("company_id")
    user.jwt_company_role = payload.get("company_role")
    user.jwt_acting_user_id = payload.get("acting_user_id")

    return user


async def get_current_admin(
    current_user: user_models.User = Depends(get_current_user),
):
    if not getattr(current_user, "jwt_is_super_admin", False):
        raise HTTPException(status_code=403, detail="Super Admin only")
    return current_user
