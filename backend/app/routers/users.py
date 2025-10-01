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
        # Input validation
        if not user.email or user.email.strip() == "":
            return {"ok": False, "error": "Email is required"}
        if not user.password or user.password.strip() == "":
            return {"ok": False, "error": "Password is required"}

        existing = await crud.get_user_by_email(db, user.email)
        if existing:
            return {"ok": False, "error": "Email already registered"}

        db_user = await crud.create_user(db, user.email, user.password)
        return {"ok": True, "msg": "User created successfully", "user_id": db_user.id}

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
        return {"ok": True, "access_token": token, "token_type": "bearer"}

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
