import os
import httpx
from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from .models import Payment, PricingPlan, PaymentStatus
from ..users.models import User


MAMO_API_KEY = os.getenv("MAMO_API_KEY")
MAMO_BASE_URL = os.getenv("MAMO_BASE_URL")

FRONTEND_BASE_URL = os.getenv("FRONTEND_BASE_URL")
FRONTEND_MAMO_SUCCESS_PATH = os.getenv("FRONTEND_MAMO_SUCCESS_PATH")
FRONTEND_MAMO_FAILURE_PATH = os.getenv("FRONTEND_MAMO_FAILURE_PATH")

SUCCESS_URL = f"{FRONTEND_BASE_URL}{FRONTEND_MAMO_SUCCESS_PATH}"
FAILURE_URL = f"{FRONTEND_BASE_URL}{FRONTEND_MAMO_FAILURE_PATH}"

INTERVAL_DAYS = {
    "month": 30,
    "year": 365,
}


async def create_payment_link(
    db: AsyncSession,
    user: User,
    plan_code: str,
):
    plan = (
        await db.execute(
            select(PricingPlan).where(
                PricingPlan.code == plan_code,
                PricingPlan.is_active == True,
            )
        )
    ).scalar_one()

    payment = Payment(
        user_id=user.id,
        pricing_plan_id=plan.id,
        amount=plan.amount,
        currency=plan.currency,
    )
    db.add(payment)
    await db.commit()
    await db.refresh(payment)

    payload = {
        "title": plan.name,
        "description": plan.name,
        "amount": plan.amount,
        "amount_currency": plan.currency,
        "return_url": SUCCESS_URL,
        "failure_return_url": FAILURE_URL,
        "enable_customer_details": True,
        "custom_data": {
            "payment_id": payment.id,
            "user_id": user.id,
            "plan_code": plan.code,
        },
    }

    FREQUENCY_MAP = {
        "month": "monthly",
        "year": "annually",
        "week": "weekly",
    }

    if plan.billing_type == "SUBSCRIPTION":
        payload["subscription"] = {
            "frequency": FREQUENCY_MAP[plan.billing_interval],
            "frequency_interval": 1,
        }

        payload["save_card"] = "required"

    else:
        payload["link_type"] = "standalone"

    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.post(
            f"{MAMO_BASE_URL}/manage_api/v1/links",
            headers={
                "Authorization": f"Bearer {MAMO_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        res.raise_for_status()
        data = res.json()

    payment.provider_payment_link_id = data["id"]
    user.subscription_status = "PENDING"

    await db.commit()

    return payment.id, data["payment_url"]


async def handle_mamopay_webhook(
    db: AsyncSession,
    payload: dict,
):
    payment_link_id = payload.get("paymentLinkId")
    status = payload.get("status")
    transaction_id = payload.get("transactionId")
    subscription_id = payload.get("subscriptionId")

    if not payment_link_id:
        return

    result = await db.execute(
        select(Payment).where(Payment.provider_payment_link_id == payment_link_id)
    )
    payment = result.scalar_one_or_none()
    if not payment:
        return

    user = await db.get(User, payment.user_id)
    plan = await db.get(PricingPlan, payment.pricing_plan_id)

    now = datetime.now(timezone.utc)

    if status == "captured":
        days = INTERVAL_DAYS.get(plan.billing_interval, 0)
        base_date = user.paid_till if user.paid_till and user.paid_till > now else now

        payment.status = PaymentStatus.SUCCESS.value
        payment.provider_transaction_id = transaction_id
        payment.provider_subscription_id = subscription_id
        payment.valid_from = base_date
        payment.valid_till = base_date + timedelta(days=days)
        payment.raw_payload = str(payload)

        user.subscription_status = "ACTIVE"
        user.paid_till = payment.valid_till
    else:
        payment.status = PaymentStatus.FAILED.value
        payment.raw_payload = str(payload)

        user.subscription_status = "EXPIRED"
        user.paid_till = None

    await db.commit()
