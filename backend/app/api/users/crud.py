from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import delete, update
from typing import Optional, Dict, Any
from ..users import models as users_models
from ..companies import models as companies_models
from ...utils.security import get_password_hash
import datetime
from app.utils.security import verify_password


async def get_user_by_email(
    db: AsyncSession, email: str
) -> Optional[users_models.User]:
    result = await db.execute(
        select(users_models.User).where(users_models.User.email == email)
    )
    return result.scalar_one_or_none()


async def get_user_by_id(db: AsyncSession, user_id: int) -> Optional[users_models.User]:
    result = await db.execute(
        select(users_models.User).where(users_models.User.id == user_id)
    )
    return result.scalar_one_or_none()


async def list_all_users(db: AsyncSession):
    result = await db.execute(select(users_models.User))
    return result.scalars().all()


async def create_user(
    db: AsyncSession,
    email: str,
    password: str,
    name: Optional[str] = None,
    created_by: Optional[int] = None,
) -> users_models.User:
    hashed = get_password_hash(password)
    first_user = await db.execute(select(users_models.User))
    first_user_exists = first_user.scalars().first() is not None
    user = users_models.User(
        email=email,
        hashed_password=hashed,
        name=name,
        is_admin=False if first_user_exists else True,
        created_by=created_by,
        updated_by=created_by,
        last_updated_by=created_by,
        is_approved=False,
        subscription_status=users_models.SubscriptionStatus.TRIAL.value,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def authenticate_user(db: AsyncSession, email: str, password: str):
    user = await get_user_by_email(db, email)
    if not user:
        return None

    if not verify_password(password, user.hashed_password):
        return None
    return user


async def delete_user(db: AsyncSession, user_id: int) -> bool:
    await db.execute(delete(users_models.User).where(users_models.User.id == user_id))
    await db.commit()
    return True


async def change_user_type(
    db: AsyncSession, user_id: int, is_admin: bool, updated_by: int
) -> Optional[users_models.User]:
    user = await get_user_by_id(db, user_id)
    if not user:
        return None
    user.is_admin = is_admin
    now = datetime.datetime.utcnow()
    user.updated_by = updated_by
    user.updated_at = now
    user.last_updated_by = updated_by
    user.last_updated_at = now
    await db.commit()
    await db.refresh(user)
    return user


async def reset_password(
    db: AsyncSession,
    email: str,
    new_password: str,
    updated_by: Optional[int] = None,
) -> Optional[users_models.User]:
    user = await get_user_by_email(db, email)
    if not user:
        return None

    user.hashed_password = get_password_hash(new_password)
    now = datetime.datetime.utcnow()

    user.updated_at = now
    user.last_updated_at = now

    if updated_by:
        user.updated_by = updated_by
        user.last_updated_by = updated_by

    await db.commit()
    await db.refresh(user)
    return user


async def update_user_fields(
    db: AsyncSession,
    user_id: int,
    fields: Dict[str, Any],
    updated_by: Optional[int] = None,
) -> Optional[users_models.User]:
    user = await get_user_by_id(db, user_id)
    if not user:
        return None

    now = datetime.datetime.utcnow()

    for key, value in fields.items():
        if hasattr(user, key) and value is not None:
            setattr(user, key, value)

    # Update audit fields
    if updated_by:
        user.updated_by = updated_by
        user.last_updated_by = updated_by
    user.updated_at = now
    user.last_updated_at = now

    await db.commit()
    await db.refresh(user)
    return user


async def deactivate_user(
    db: AsyncSession, user_id: int, updated_by: int
) -> Optional[users_models.User]:
    user = await get_user_by_id(db, user_id)
    if not user:
        return None

    user.is_approved = False
    now = datetime.datetime.utcnow()
    user.updated_by = updated_by
    user.last_updated_by = updated_by
    user.updated_at = now
    user.last_updated_at = now

    await db.commit()
    await db.refresh(user)
    return user


async def get_user_companies(db: AsyncSession, user_id: int):
    stmt = (
        select(companies_models.Company)
        .join(
            companies_models.CompanyUser,
            companies_models.Company.id == companies_models.CompanyUser.company_id,
        )
        .where(companies_models.CompanyUser.user_id == user_id)
    )
    result = await db.execute(stmt)
    return result.scalars().all()


async def set_user_accountant(
    db: AsyncSession,
    user_id: int,
    is_accountant: bool,
    updated_by: Optional[int] = None,
) -> Optional[users_models.User]:
    user = await get_user_by_id(db, user_id)
    if not user:
        return None

    user.is_accountant = bool(is_accountant)
    now = datetime.datetime.utcnow()

    if updated_by:
        user.updated_by = updated_by
        user.last_updated_by = updated_by

    user.updated_at = now
    user.last_updated_at = now

    await db.commit()
    await db.refresh(user)
    return user


async def set_connection_status(
    db: AsyncSession,
    user_id: int,
    field: str,
    value: bool
) -> bool:
    # Validate allowed fields for safety
    allowed_fields = {"is_qb_connected", "is_zb_connected"}
    if field not in allowed_fields:
        raise ValueError(f"Invalid connection field: {field}")

    stmt = (
        update(users_models.User)
        .where(users_models.User.id == user_id)
        .values({field: value})
        .execution_options(synchronize_session="fetch")
    )

    await db.execute(stmt)
    await db.commit()
    return True

async def get_connection_status(
    db: AsyncSession,
    user_id: int,
    field: str
) -> bool:
    allowed_fields = {"is_qb_connected", "is_zb_connected"}
    if field not in allowed_fields:
        raise ValueError(f"Invalid connection field: {field}")

    user = await get_user_by_id(db, user_id)
    if not user:
        return False
    
    return getattr(user, field)

# ---- QuickBooks ----
async def mark_qb_connected(db: AsyncSession, user_id: int):
    return await set_connection_status(db, user_id, "is_qb_connected", True)

async def mark_qb_disconnected(db: AsyncSession, user_id: int):
    return await set_connection_status(db, user_id, "is_qb_connected", False)

async def get_qb_connection_status(db: AsyncSession, user_id: int):
    return await get_connection_status(db, user_id, "is_qb_connected")


# ---- Zoho Books ----
async def mark_zb_connected(db: AsyncSession, user_id: int):
    return await set_connection_status(db, user_id, "is_zb_connected", True)

async def mark_zb_disconnected(db: AsyncSession, user_id: int):
    return await set_connection_status(db, user_id, "is_zb_connected", False)

async def get_zb_connection_status(db: AsyncSession, user_id: int):
    return await get_connection_status(db, user_id, "is_zb_connected")
