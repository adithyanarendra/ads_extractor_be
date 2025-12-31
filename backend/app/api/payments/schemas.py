from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class PricingPlanBase(BaseModel):
    code: str
    name: str
    amount: float
    currency: str
    billing_type: str
    billing_interval: Optional[str] = None
    is_active: Optional[bool] = True


class PricingPlanCreate(PricingPlanBase):
    pass


class PricingPlanUpdate(BaseModel):
    code: Optional[str] = None
    name: Optional[str] = None
    amount: Optional[float] = None
    currency: Optional[str] = None
    billing_type: Optional[str] = None
    billing_interval: Optional[str] = None
    is_active: Optional[bool] = None


class PricingPlanOut(PricingPlanBase):
    id: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class CreatePaymentResponse(BaseModel):
    payment_id: int
    payment_url: str


class PaymentStatusOut(BaseModel):
    subscription_status: str
    paid_till: Optional[datetime]
    trial_ends_at: Optional[datetime] = None
    trial_active: Optional[bool] = None
    skip_payment_check: Optional[bool] = None
