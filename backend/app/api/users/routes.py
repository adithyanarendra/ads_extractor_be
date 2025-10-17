from fastapi import APIRouter, Depends, Header
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from pydantic import BaseModel
import asyncio

from ...core import auth
from . import schemas as users_schemas
from . import crud
from ...core.database import get_db


router = APIRouter(prefix="/users", tags=["users"])


@router.post("/signup", status_code=201)
async def signup(
    user: users_schemas.UserCreate,
    db: AsyncSession = Depends(get_db),
    authorization: Optional[str] = Header(None),
):
    try:
        if not user.email or user.email.strip() == "":
            return {"ok": False, "error": "Email is required"}
        if not user.password or user.password.strip() == "":
            return {"ok": False, "error": "Password is required"}

        existing = await crud.get_user_by_email(db, user.email)
        if existing:
            return {"ok": False, "error": "Email already registered"}

        created_by_user_id = None
        if authorization and authorization.startswith("Bearer "):
            token = authorization.split(" ")[1]
            try:
                current_user = await auth.get_current_user_from_token(token, db)
                created_by_user_id = current_user.id
            except Exception:
                created_by_user_id = None

        db_user = await crud.create_user(
            db, user.email, user.password, name=user.name, created_by=created_by_user_id
        )
        return {
            "ok": True,
            "msg": "User created successfully",
            "user_id": db_user.id,
            "name": db_user.name,
            "admin": db_user.is_admin,
        }

    except SQLAlchemyError as e:
        return {
            "ok": False,
            "error": "Database error",
            "details": str(e.__cause__ or e),
        }
    except Exception as e:
        return {"ok": False, "error": "Unexpected error", "details": str(e)}


@router.post("/login")
async def login(user: users_schemas.UserLogin, db: AsyncSession = Depends(get_db)):
    try:
        if not user.email or user.email.strip() == "":
            return {"ok": False, "error": "Email is required"}
        if not user.password or user.password.strip() == "":
            return {"ok": False, "error": "Password is required"}

        db_user = await crud.authenticate_user(db, user.email, user.password)
        if not db_user:
            return {"ok": False, "error": "Invalid credentials"}

        token = auth.create_access_token({"sub": db_user.email})
        return {
            "ok": True,
            "access_token": token,
            "token_type": "bearer",
            "name": db_user.name,
            "admin": db_user.is_admin,
        }

    except SQLAlchemyError as e:
        return {
            "ok": False,
            "error": "Database error",
            "details": str(e.__cause__ or e),
        }
    except Exception as e:
        return {"ok": False, "error": "Unexpected error", "details": str(e)}


@router.get("/logout")
async def logout():
    # client should simply delete token; server-side stateless JWT can't easily be "logged out"
    return {"ok": True, "msg": "Logged out"}


@router.get("/all")
async def get_all_users(
    db: AsyncSession = Depends(get_db), current_admin=Depends(auth.get_current_admin)
):
    users = await crud.list_all_users(db)

    async def get_user_email(user_id: Optional[int]) -> Optional[str]:
        if not user_id:
            return None
        user = await crud.get_user_by_id(db, user_id)
        return user.email if user else None

    users_data = []

    for u in users:
        created_by_email, updated_by_email, last_updated_by_email = (
            await asyncio.gather(
                get_user_email(u.created_by),
                get_user_email(u.updated_by),
                get_user_email(u.last_updated_by),
            )
        )

        users_data.append(
            {
                "id": u.id,
                "email": u.email,
                "is_admin": u.is_admin,
                "created_by": created_by_email,
                "created_at": u.created_at,
                "updated_by": updated_by_email,
                "updated_at": u.updated_at,
                "last_updated_by": last_updated_by_email,
                "last_updated_at": u.last_updated_at,
            }
        )
    return {"ok": True, "users": users_data}


@router.delete("/delete/{user_id}")
async def delete_user_account(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin=Depends(auth.get_current_admin),
):
    user = await crud.get_user_by_id(db, user_id)
    if not user:
        return {"ok": False, "error": "User not found"}
    await crud.delete_user(db, user_id)
    return {"ok": True, "msg": f"User {user.email} deleted"}


@router.delete("/delete_admin/{user_id}")
async def delete_admin_account(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin=Depends(auth.get_current_admin),
):
    user = await crud.get_user_by_id(db, user_id)
    if not user:
        return {"ok": False, "error": "User not found"}
    if not user.is_admin:
        return {"ok": False, "error": "Not an admin account"}
    if user.id == current_admin.id:
        return {"ok": False, "error": "You cannot delete yourself"}
    await crud.delete_user(db, user_id)
    return {"ok": True, "msg": f"Admin {user.email} deleted"}


@router.put("/change_type/{user_id}")
async def change_user_type(
    user_id: int,
    payload: users_schemas.ChangeUserTypeRequest,
    db: AsyncSession = Depends(get_db),
    current_admin=Depends(auth.get_current_admin),
):
    user = await crud.change_user_type(db, user_id, payload.is_admin, current_admin.id)
    if not user:
        return {"ok": False, "error": "User not found"}
    return {"ok": True, "msg": f"User {user.email} updated to admin={payload.is_admin}"}


@router.post("/reset_password")
async def reset_password(
    payload: users_schemas.ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
    authorization: Optional[str] = Header(None),
):
    try:
        if not payload.email or payload.email.strip() == "":
            return {"ok": False, "error": "Email is required"}
        if not payload.new_password or payload.new_password.strip() == "":
            return {"ok": False, "error": "New password is required"}

        updated_by_user_id = None

        if authorization and authorization.startswith("Bearer "):
            token = authorization.split(" ")[1]
            try:
                current_user = await auth.get_current_user_from_token(token, db)
                updated_by_user_id = current_user.id
            except Exception:
                updated_by_user_id = None

        updated_user = await crud.reset_password(
            db,
            email=payload.email,
            new_password=payload.new_password,
            updated_by=updated_by_user_id,
        )

        if not updated_user:
            return {"ok": False, "error": "User not found"}

        return {
            "ok": True,
            "msg": "Password reset successful",
            "updated_by": updated_by_user_id,
        }

    except SQLAlchemyError as e:
        return {
            "ok": False,
            "error": "Database error",
            "details": str(e.__cause__ or e),
        }
    except Exception as e:
        return {"ok": False, "error": "Unexpected error", "details": str(e)}


@router.put("/update")
async def update_user(
    payload: users_schemas.UpdateUserRequest,
    db: AsyncSession = Depends(get_db),
    authorization: Optional[str] = Header(None),
):
    if not authorization or not authorization.startswith("Bearer "):
        return {"ok": False, "error": "Authorization header required"}

    token = authorization.split(" ")[1]
    try:
        current_user = await auth.get_current_user_from_token(token, db)
    except Exception:
        return {"ok": False, "error": "Invalid token"}

    target_user_id = payload.user_id if hasattr(payload, "user_id") else current_user.id

    if target_user_id != current_user.id and not current_user.is_admin:
        return {"ok": False, "error": "Not authorized to update other users"}

    target_user = await crud.get_user_by_id(db, target_user_id)
    if not target_user:
        return {"ok": False, "error": "Target user not found"}

    updated_fields = payload.dict(exclude_unset=True, exclude={"user_id"})
    if not updated_fields:
        return {"ok": False, "error": "No fields to update"}

    updated_user = await crud.update_user_fields(
        db, target_user.id, updated_fields, updated_by=current_user.id
    )

    return {
        "ok": True,
        "msg": "User updated successfully",
        "user": {
            "id": updated_user.id,
            "email": updated_user.email,
            "name": updated_user.name,
            "is_admin": updated_user.is_admin,
        },
    }
