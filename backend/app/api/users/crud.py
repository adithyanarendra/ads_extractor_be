from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import delete
from typing import Optional, Dict, Any
from ..users import models as users_models
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
