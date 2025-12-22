import enum
from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    DateTime,
    ForeignKey,
    Text,
    Boolean,
)
from sqlalchemy.sql import func
from ...core.database import Base


class PaymentStatus(str, enum.Enum):
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class PricingPlan(Base):
    __tablename__ = "pricing_plans"

    id = Column(Integer, primary_key=True)
    code = Column(String, nullable=False)
    name = Column(String, nullable=False)

    amount = Column(Float, nullable=False)
    currency = Column(String(3), nullable=False)

    billing_type = Column(String, nullable=False)
    billing_interval = Column(String, nullable=True)

    scope = Column(String, default="USER")
    is_active = Column(Boolean, nullable=False, server_default="true")

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True)

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    pricing_plan_id = Column(Integer, ForeignKey("pricing_plans.id"))

    status = Column(String, default=PaymentStatus.PENDING.value)

    provider = Column(String, default="MAMOPAY")
    provider_payment_link_id = Column(String, index=True)
    provider_transaction_id = Column(String)
    provider_subscription_id = Column(String)

    amount = Column(Float, nullable=False)
    currency = Column(String(3), nullable=False)

    valid_from = Column(DateTime(timezone=True))
    valid_till = Column(DateTime(timezone=True))

    raw_payload = Column(Text)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
