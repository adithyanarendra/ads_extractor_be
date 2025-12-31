from fastapi import APIRouter, Depends, Request, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from ...core.database import get_db
from ...core.auth import get_current_user, get_current_admin
from .service import create_payment_link, handle_mamopay_webhook
from ...core.enforcement import is_trial_active, trial_end_for_user
from .schemas import (
    CreatePaymentResponse,
    PaymentStatusOut,
    PricingPlanCreate,
    PricingPlanOut,
    PricingPlanUpdate,
)
from .models import PricingPlan

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


@router.get("/plans", response_model=list[PricingPlanOut])
async def list_active_plans(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(PricingPlan).where(PricingPlan.is_active == True)
    )
    return result.scalars().all()


@router.get("/plans/admin", response_model=list[PricingPlanOut])
async def list_all_plans(
    db: AsyncSession = Depends(get_db),
    current_admin=Depends(get_current_admin),
):
    result = await db.execute(select(PricingPlan))
    return result.scalars().all()


@router.post("/plans", response_model=PricingPlanOut)
async def create_plan(
    payload: PricingPlanCreate,
    db: AsyncSession = Depends(get_db),
    current_admin=Depends(get_current_admin),
):
    existing = await db.execute(
        select(PricingPlan).where(PricingPlan.code == payload.code)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Plan code already exists")

    plan = PricingPlan(**payload.dict())
    db.add(plan)
    await db.commit()
    await db.refresh(plan)
    return plan


@router.put("/plans/{plan_id}", response_model=PricingPlanOut)
async def update_plan(
    plan_id: int,
    payload: PricingPlanUpdate,
    db: AsyncSession = Depends(get_db),
    current_admin=Depends(get_current_admin),
):
    plan = await db.get(PricingPlan, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")

    update_data = payload.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(plan, key, value)

    await db.commit()
    await db.refresh(plan)
    return plan


@router.delete("/plans/{plan_id}")
async def deactivate_plan(
    plan_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin=Depends(get_current_admin),
):
    plan = await db.get(PricingPlan, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")

    plan.is_active = False
    await db.commit()
    return {"ok": True}


@router.post("/webhook")
async def mamopay_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    payload = await request.json()
    await handle_mamopay_webhook(db, payload)
    return {"ok": True}
