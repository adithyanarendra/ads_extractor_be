from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    is_admin = Column(Boolean, default=False)

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

    invoices = relationship(
        "Invoice", back_populates="owner", cascade="all, delete-orphan"
    )


class Invoice(Base):
    __tablename__ = "invoices"

    id = Column(Integer, primary_key=True, index=True)
    file_path = Column(String, nullable=False)
    invoice_number = Column(String, nullable=True)
    invoice_date = Column(String, nullable=True)
    vendor_name = Column(String, nullable=True)
    trn_vat_number = Column(String, nullable=True)
    before_tax_amount = Column(String, nullable=True)
    tax_amount = Column(String, nullable=True)
    total = Column(String, nullable=True)
    reviewed = Column(Boolean, default=False)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    owner = relationship("User", back_populates="invoices")
