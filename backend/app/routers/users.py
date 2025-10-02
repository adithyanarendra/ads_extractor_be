from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app import models, schemas, auth, crud
from app.database import get_db

router = APIRouter(prefix="/users", tags=["users"])


@router.post("/signup", status_code=201)
async def signup(user: schemas.UserCreate, db: AsyncSession = Depends(get_db)):
    try:
        if not user.email or user.email.strip() == "":
            return {"ok": False, "error": "Email is required"}
        if not user.password or user.password.strip() == "":
            return {"ok": False, "error": "Password is required"}

        existing = await crud.get_user_by_email(db, user.email)
        if existing:
            return {"ok": False, "error": "Email already registered"}

        db_user = await crud.create_user(db, user.email, user.password)
        return {
            "ok": True,
            "msg": "User created successfully",
            "user_id": db_user.id,
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
async def login(user: schemas.UserLogin, db: AsyncSession = Depends(get_db)):
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
    users_data = [
        {
            "id": u.id,
            "email": u.email,
            "is_admin": u.is_admin,
            "created_by": u.created_by,
            "created_at": u.created_at,
            "updated_by": u.updated_by,
            "updated_at": u.updated_at,
            "last_updated_by": u.last_updated_by,
            "last_updated_at": u.last_updated_at,
        }
        for u in users
    ]
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
    is_admin: bool,
    db: AsyncSession = Depends(get_db),
    current_admin=Depends(auth.get_current_admin),
):
    user = await crud.change_user_type(db, user_id, is_admin, current_admin.id)
    if not user:
        return {"ok": False, "error": "User not found"}
    return {"ok": True, "msg": f"User {user.email} updated to admin={is_admin}"}
