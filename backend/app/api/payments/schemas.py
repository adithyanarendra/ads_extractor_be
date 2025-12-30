from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class CreatePaymentResponse(BaseModel):
    payment_id: int
    payment_url: str


class PaymentStatusOut(BaseModel):
    subscription_status: str
    paid_till: Optional[datetime]
    trial_ends_at: Optional[datetime] = None
    trial_active: Optional[bool] = None
    skip_payment_check: Optional[bool] = None
