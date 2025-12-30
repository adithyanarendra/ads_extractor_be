from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...core.auth import get_current_user
from .service import create_payment_link, handle_mamopay_webhook
from ...core.enforcement import is_trial_active, trial_end_for_user
from .schemas import CreatePaymentResponse, PaymentStatusOut

router = APIRouter(prefix="/payments", tags=["payments"])


@router.post("/buy/{plan_code}", response_model=CreatePaymentResponse)
async def buy_plan(
    plan_code: str,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    pid, url = await create_payment_link(db, user, plan_code)
    return {"payment_id": pid, "payment_url": url}


@router.get("/status", response_model=PaymentStatusOut)
async def payment_status(user=Depends(get_current_user)):
    trial_end = trial_end_for_user(user)
    return {
        "subscription_status": user.subscription_status,
        "paid_till": user.paid_till,
        "trial_ends_at": trial_end,
        "trial_active": is_trial_active(user),
        "skip_payment_check": user.skip_payment_check,
    }


@router.post("/webhook")
async def mamopay_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    payload = await request.json()
    await handle_mamopay_webhook(db, payload)
    return {"ok": True}
