from pydantic import BaseModel
from typing import Optional


class CreatePaymentResponse(BaseModel):
    payment_id: int
    payment_url: str


class PaymentStatusOut(BaseModel):
    subscription_status: str
    paid_till: Optional[str]
