from datetime import datetime, timedelta, timezone
from fastapi import Depends, HTTPException

from .auth import get_current_user


def _normalize_now(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def trial_end_for_user(user):
    if user.signup_at:
        base = _normalize_now(user.signup_at)
        return base + timedelta(days=7)
    return None


def is_trial_active(user) -> bool:
    trial_end = trial_end_for_user(user)
    if not trial_end:
        return False
    now = datetime.now(timezone.utc)
    return now <= trial_end


def has_active_subscription(user) -> bool:
    if user.subscription_status != "ACTIVE":
        return False
    if user.paid_till is None:
        return True
    now = datetime.now(timezone.utc)
    paid_till = _normalize_now(user.paid_till)
    return paid_till >= now


async def require_active_subscription(current_user=Depends(get_current_user)):
    if (
        getattr(current_user, "skip_payment_check", False)
        or getattr(current_user, "jwt_is_super_admin", False)
        or getattr(current_user, "jwt_is_accountant", False)
        or getattr(current_user, "is_admin", False)
    ):
        return current_user

    if is_trial_active(current_user):
        return current_user

    if has_active_subscription(current_user):
        return current_user

    raise HTTPException(
        status_code=402,
        detail={"message": "Payment required", "redirect": "/payments"},
    )
