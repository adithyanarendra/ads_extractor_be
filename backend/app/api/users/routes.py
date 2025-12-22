from fastapi import APIRouter, Depends, Header, Body, HTTPException, Query
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from datetime import datetime
from typing import Optional
from ...core import auth
from . import crud
from . import models as users_models
from ...core.database import get_db
from ..companies import crud as companies_crud
from ..companies.models import CompanyUser
from . import schemas as users_schemas
from app.core.auth import get_current_user
from ..invoices.models import Invoice
from ..user_docs.models import UserDocs

from sqlalchemy import func, or_



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
        creator = None
        if authorization and authorization.startswith("Bearer "):
            token = authorization.split(" ")[1]
            try:
                creator = await auth.get_current_user_from_token(token, db)
                created_by_user_id = creator.id
            except Exception:
                created_by_user_id = None

        db_user = await crud.create_user(
            db,
            user.email,
            user.password,
            name=user.name,
            created_by=created_by_user_id,
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
    db_user = await crud.authenticate_user(db, user.email, user.password)
    if not db_user:
        return {"ok": False, "error": "Invalid credentials"}
    
    db_user.last_login_at = func.now()
    await db.commit()
    await db.refresh(db_user)

    is_super_admin = db_user.is_admin or db_user.is_super_admin

    companies = await crud.get_user_companies(db, db_user.id)

    base_token = auth.create_access_token(
        {
            "sub": db_user.email,
            "uid": db_user.id,
            "is_admin": is_super_admin,
            "is_accountant": db_user.is_accountant,
        }
    )

    if len(companies) == 0:
        return {
            "ok": True,
            "access_token": base_token,
            "token_type": "bearer",
            "name": db_user.name,
            "is_super_admin": is_super_admin,
            "is_accountant": db_user.is_accountant,
            "companies": [],
            "choose_company": False,
        }

    if len(companies) == 1:
        company = companies[0]

        cu = await db.execute(
            select(CompanyUser).where(
                CompanyUser.company_id == company.id, CompanyUser.user_id == db_user.id
            )
        )
        cu = cu.scalar_one()
        role = "admin" if cu.company_admin else "user"

        final_token = auth.create_access_token(
            {
                "sub": db_user.email,
                "uid": db_user.id,
                "is_admin": is_super_admin,
                "is_accountant": db_user.is_accountant,
                "company_id": company.id,
                "company_role": role,
            }
        )
        return {
            "ok": True,
            "access_token": final_token,
            "token_type": "bearer",
            "name": db_user.name,
            "is_super_admin": is_super_admin,
            "is_accountant": db_user.is_accountant,
            "companies": [{"id": company.id, "name": company.name}],
            "choose_company": False,
            "company_id": company.id,
            "company_role": role,
        }

    return {
        "ok": True,
        "access_token": base_token,
        "token_type": "bearer",
        "name": db_user.name,
        "is_super_admin": is_super_admin,
        "is_accountant": db_user.is_accountant,
        "companies": [{"id": c.id, "name": c.name} for c in companies],
        "choose_company": True,
    }


@router.post("/accountant/select_client")
async def accountant_select_client(
    payload: dict,
    db: AsyncSession = Depends(get_db),
    authorization: Optional[str] = Header(None),
):
    if not authorization or not authorization.startswith("Bearer "):
        return {"ok": False, "error": "Authorization required"}
    token = authorization.split(" ")[1]
    current_user = await auth.get_current_user_from_token(token, db)

    if not (
        getattr(current_user, "jwt_is_super_admin", False) or current_user.is_admin
    ):
        if not getattr(current_user, "jwt_is_accountant", False):
            return {"ok": False, "error": "Not authorized"}

    user_id = payload.get("user_id")
    if not user_id:
        return {"ok": False, "error": "user_id is required"}

    target = await crud.get_user_by_id(db, user_id)
    if not target:
        return {"ok": False, "error": "Target user not found"}

    if target.is_admin or target.is_super_admin or target.is_accountant:
        return {"ok": False, "error": "Cannot act as privileged account"}

    final_token = auth.create_access_token(
        {
            "sub": current_user.email,
            "uid": current_user.id,
            "is_admin": current_user.is_super_admin,
            "is_accountant": current_user.is_accountant,
            "acting_user_id": target.id,
        }
    )

    return {"ok": True, "access_token": final_token, "acting_user_id": target.id}


@router.get("/accountant/users")
async def accountant_list_users(
    db: AsyncSession = Depends(get_db),
    authorization: Optional[str] = Header(None),
):
    if not authorization or not authorization.startswith("Bearer "):
        return {"ok": False, "error": "Authorization required"}
    token = authorization.split(" ")[1]
    current_user = await auth.get_current_user_from_token(token, db)

    if not (
        getattr(current_user, "jwt_is_accountant", False) or current_user.is_super_admin
    ):
        return {"ok": False, "error": "Not authorized"}

    users = await crud.list_all_users(db)
    out = [{"id": u.id, "name": u.name or u.email, "email": u.email} for u in users if (not u.is_admin and not u.is_accountant)]
    return {"ok": True, "users": out}


@router.put("/make_accountant/{user_id}")
async def make_accountant(
    user_id: int,
    payload: dict = Body(...),
    db: AsyncSession = Depends(get_db),
    authorization: Optional[str] = Header(None),
):
    if not authorization or not authorization.startswith("Bearer "):
        return {"ok": False, "error": "Authorization required"}
    token = authorization.split(" ")[1]
    current_user = await auth.get_current_user_from_token(token, db)

    if not (
        current_user.is_admin or getattr(current_user, "jwt_is_super_admin", False)
    ):
        return {"ok": False, "error": "Not authorized to change accountant flag"}

    is_accountant_val = payload.get("is_accountant")
    if is_accountant_val is None:
        return {"ok": False, "error": "is_accountant boolean required in body"}

    updated_user = await crud.set_user_accountant(
        db, user_id, bool(is_accountant_val), updated_by=current_user.id
    )
    if not updated_user:
        return {"ok": False, "error": "User not found"}

    return {
        "ok": True,
        "msg": f"User {updated_user.email} is_accountant set to {updated_user.is_accountant}",
        "user": {
            "id": updated_user.id,
            "email": updated_user.email,
            "is_accountant": updated_user.is_accountant,
        },
    }


@router.get("/logout")
async def logout():
    # client should simply delete token; server-side stateless JWT can't easily be "logged out"
    return {"ok": True, "msg": "Logged out"}


@router.get("/all")
async def get_all_users(
    db: AsyncSession = Depends(get_db), current_admin=Depends(auth.get_current_admin)
):
    users = await crud.list_all_users(db)

    data = [
        {
            "id": u.id,
            "email": u.email,
            "is_admin": u.is_admin,
            "is_accountant": u.is_accountant,
        }
        for u in users
    ]

    return {"ok": True, "users": data}


@router.get("/details/{user_id}")
async def get_user_details(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin=Depends(auth.get_current_admin),
):
    user = await crud.get_user_by_id(db, user_id)
    if not user:
        return {"ok": False, "error": "User not found"}

    ids = [
        uid for uid in [user.created_by, user.updated_by, user.last_updated_by] if uid
    ]
    lookup = {}

    if ids:
        result = await db.execute(
            select(users_models.User.id, users_models.User.email).where(
                users_models.User.id.in_(ids)
            )
        )
        lookup = {uid: email for uid, email in result.all()}

    return {
        "ok": True,
        "user": {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "is_admin": user.is_admin,
            "is_accountant": user.is_accountant,
            "is_super_admin": user.is_super_admin,
            "is_approved": user.is_approved,
            "created_by": lookup.get(user.created_by),
            "created_at": user.created_at,
            "updated_by": lookup.get(user.updated_by),
            "updated_at": user.updated_at,
            "last_updated_by": lookup.get(user.last_updated_by),
            "last_updated_at": user.last_updated_at,
            "signup_at": user.signup_at,
        },
    }


@router.delete("/delete/{user_id}")
async def delete_user_account(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    authorization: Optional[str] = Header(None),
):
    if not authorization or not authorization.startswith("Bearer "):
        return {"ok": False, "error": "Authorization required"}

    token = authorization.split(" ")[1]
    current_user = await auth.get_current_user_from_token(token, db)

    if current_user.id == user_id:
        return {"ok": False, "error": "You cannot delete yourself"}

    target = await crud.get_user_by_id(db, user_id)
    if not target:
        return {"ok": False, "error": "User not found"}

    if getattr(current_user, "jwt_is_accountant", False):

        if target.is_admin or target.is_super_admin or target.is_accountant:
            return {"ok": False, "error": "Not authorized to delete privileged users"}

        await crud.delete_user(db, user_id)
        return {"ok": True, "msg": f"User {target.email} deleted by accountant"}

    if current_user.is_admin or getattr(current_user, "jwt_is_super_admin", False):
        await crud.delete_user(db, user_id)
        return {"ok": True, "msg": f"User {target.email} deleted"}

    return {"ok": False, "error": "Not authorized"}


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

    target_user_id = (
        payload.user_id
        if hasattr(payload, "user_id") and payload.user_id
        else current_user.id
    )

    if target_user_id != current_user.id:
        if current_user.is_admin or getattr(current_user, "jwt_is_super_admin", False):
            pass
        elif getattr(current_user, "jwt_is_accountant", False):

            target = await crud.get_user_by_id(db, target_user_id)
            if not target:
                return {"ok": False, "error": "Target user not found"}
            if target.is_admin or target.is_accountant or target.is_super_admin:
                return {
                    "ok": False,
                    "error": "Not authorized to update privileged users",
                }
        else:
            return {"ok": False, "error": "Not authorized to update other users"}

    target_user = await crud.get_user_by_id(db, target_user_id)
    if not target_user:
        return {"ok": False, "error": "Target user not found"}

    updated_fields = payload.dict(exclude_unset=True, exclude={"user_id"})
    if not updated_fields:
        return {"ok": False, "error": "No fields to update"}

    if "is_accountant" in updated_fields:
        if not (
            current_user.is_admin or getattr(current_user, "jwt_is_super_admin", False)
        ):
            return {"ok": False, "error": "Not authorized to change accountant flag"}

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
            "is_accountant": updated_user.is_accountant,
        },
    }


@router.get("/to_be_approved")
async def get_unapproved_users(
    db: AsyncSession = Depends(get_db),
    current_admin=Depends(auth.get_current_admin),
):
    result = await db.execute(
        select(users_models.User).where(users_models.User.is_approved == False)
    )
    users = result.scalars().all()
    users_data = [
        {"id": u.id, "email": u.email, "signup_at": u.signup_at} for u in users
    ]
    return {"ok": True, "users": users_data}


@router.post("/approve/{user_id}")
async def approve_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin=Depends(auth.get_current_admin),
):
    user = await crud.get_user_by_id(db, user_id)
    if not user:
        return {"ok": False, "error": "User not found"}

    user.is_approved = True
    user.updated_at = datetime.utcnow()
    user.last_updated_at = datetime.utcnow()
    user.updated_by = current_admin.id
    user.last_updated_by = current_admin.id

    await db.commit()
    await db.refresh(user)
    return {"ok": True, "msg": f"User {user.email} approved"}


@router.post("/deactivate/{user_id}")
async def deactivate_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin=Depends(auth.get_current_admin),
):
    user = await crud.deactivate_user(db, user_id, current_admin.id)
    if not user:
        return {"ok": False, "error": "User not found"}
    return {"ok": True, "msg": f"User {user.email} deactivated (login revoked)"}


@router.post("/accountant/reset_client")
async def accountant_reset_client(
    db: AsyncSession = Depends(get_db),
    authorization: Optional[str] = Header(None),
):
    if not authorization or not authorization.startswith("Bearer "):
        return {"ok": False, "error": "Authorization required"}

    token = authorization.split(" ")[1]
    current_user = await auth.get_current_user_from_token(token, db)

    if not (
        getattr(current_user, "jwt_is_accountant", False)
        or current_user.is_admin
        or current_user.is_super_admin
    ):
        return {"ok": False, "error": "Not authorized"}

    clean_token = auth.create_access_token(
        {
            "sub": current_user.email,
            "uid": current_user.id,
            "is_admin": current_user.is_super_admin,
            "is_accountant": current_user.is_accountant,
            "company_id": current_user.jwt_company_id,
            "company_role": current_user.jwt_company_role,
        }
    )

    return {"ok": True, "access_token": clean_token}

@router.post("/select_company")
async def select_company(
    payload: users_schemas.SelectCompanyPayload,
    db: AsyncSession = Depends(get_db),
    authorization: Optional[str] = Header(None),
):
    if not authorization or not authorization.startswith("Bearer "):
        return {"ok": False, "error": "Authorization required"}

    token = authorization.split(" ")[1]
    user = await auth.get_current_user_from_token(token, db)

    if not await companies_crud.is_user_in_company(db, user.id, payload.company_id):
        return {"ok": False, "error": "Not part of this company"}

    assoc = await db.execute(
        select(CompanyUser).where(
            CompanyUser.company_id == payload.company_id,
            CompanyUser.user_id == user.id,
        )
    )
    assoc = assoc.scalar_one()
    role = "admin" if assoc.company_admin else "user"

    final_token = auth.create_access_token(
        {
            "sub": user.email,
            "uid": user.id,
            "is_admin": user.is_super_admin,
            "company_id": payload.company_id,
            "company_role": role,
        }
    )

    return {
        "ok": True,
        "access_token": final_token,
        "token_type": "bearer",
        "company_id": payload.company_id,
        "company_role": role,
    }

@router.get("/info")
async def get_user_info(
    db: AsyncSession = Depends(get_db),
    authorization: Optional[str] = Header(None),
):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization required")

    token = authorization.split(" ")[1]
    user = await auth.get_current_user_from_token(token, db)

    return {
        "ok": True,
        "user": {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "currency": user.currency,  
        },
    }

@router.get("/user_currency")
async def get_user_currency(
    db: AsyncSession = Depends(get_db),
    authorization: Optional[str] = Header(None),
):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization required")

    token = authorization.split(" ")[1]
    user = await auth.get_current_user_from_token(token, db)

    return {
        "currency": user.currency
    }

@router.get("/clients")
async def list_clients_for_accountant(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),

    q: Optional[str] = Query(None, description="Search by name or email"),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
):
    if not getattr(current_user, "jwt_is_accountant", False):
        raise HTTPException(status_code=403, detail="Accountant access only")

    offset = (page - 1) * page_size

    filters = [
        users_models.User.is_admin == False,
        users_models.User.is_accountant == False,
    ]

    if q:
        search = f"%{q.lower()}%"
        filters.append(
            or_(
                func.lower(users_models.User.email).like(search),
                func.lower(users_models.User.name).like(search),
            )
        )

    total_result = await db.execute(
        select(func.count(users_models.User.id)).where(*filters)
    )
    total = total_result.scalar() or 0

    result = await db.execute(
        select(users_models.User)
        .where(*filters)
        .order_by(users_models.User.id.desc())
        .offset(offset)
        .limit(page_size)
    )

    users = result.scalars().all()
    clients = []

    for user in users:
        expense_count = await db.scalar(
            select(func.count(Invoice.id)).where(
                Invoice.owner_id == user.id,
                Invoice.type == "expense",
                Invoice.is_deleted == False,
            )
        )

        sales_count = await db.scalar(
            select(func.count(Invoice.id)).where(
                Invoice.owner_id == user.id,
                Invoice.type == "sales",
                Invoice.is_deleted == False,
            )
        )

        doc_count = await db.scalar(
            select(func.count(UserDocs.id)).where(
                UserDocs.user_id == user.id
            )
        )

        clients.append(
            {
                "id": user.id,
                "name": user.name,
                "email": user.email,
                "expense_count": expense_count or 0,
                "sales_count": sales_count or 0,
                "doc_count": doc_count or 0,
                "last_login": None,
                "qb_connected": bool(user.is_qb_connected),
                "zb_connected": bool(user.is_zb_connected),
            }
        )

    return {
        "ok": True,
        "page": page,
        "page_size": page_size,
        "total": total,
        "pages": (total + page_size - 1) // page_size,
        "clients": clients,
    }