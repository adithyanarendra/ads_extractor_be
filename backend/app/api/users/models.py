from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum
from app.api.lov.currency import CurrencyEnum


from ...core.database import Base

# below are called but unused for not found issues - *DO NOT REMOVE*
from ..user_docs.models import UserDocs
from ..reports.models import Report
from ..companies.models import CompanyUser
from ..invoices.models import Invoice


class SubscriptionStatus(str, enum.Enum):
    TRIAL = "TRIAL"
    NONE = "NONE"
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    name = Column(String, nullable=True)

    is_admin = Column(Boolean, default=False)
    is_super_admin = Column(Boolean, default=False, nullable=False)
    is_accountant = Column(Boolean, default=False, nullable=False)
    role = Column(String, nullable=True)

    is_approved = Column(Boolean, default=False)

    is_qb_connected = Column(Boolean, default=False, nullable=False)
    is_zb_connected = Column(Boolean, default=False, nullable=False)

    signup_at = Column(DateTime(timezone=True), server_default=func.now())
    skip_payment_check = Column(Boolean, default=False, nullable=False)

    # Audit fields
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    last_updated_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    last_updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    last_login_at = Column(
        DateTime(timezone=True),
        nullable=True
    )  

    currency = Column(String(3), nullable=True, server_default=CurrencyEnum.AED.value)

    subscription_status = Column(
        String(20),
        nullable=False,
        server_default=SubscriptionStatus.NONE.value,
        index=True,
    )

    paid_till = Column(DateTime(timezone=True), nullable=True)

    invoices = relationship(
        "Invoice",
        back_populates="owner",
        cascade="all, delete-orphan",
        foreign_keys="Invoice.owner_id",
    )

    batches = relationship(
        "Batch", back_populates="owner", cascade="all, delete-orphan"
    )

    documents = relationship(
        "UserDocs",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    reports = relationship(
        "Report", back_populates="user", cascade="all, delete-orphan"
    )
    companies_assoc = relationship(
        "CompanyUser",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
        foreign_keys="CompanyUser.user_id",
    )
