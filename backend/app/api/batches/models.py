from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship

from ...core.database import Base
from ..invoices.models import Invoice


class Batch(Base):
    __tablename__ = "batches"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String, nullable=False, unique=True)
    locked = Column(Boolean, default=False)
    created_at = Column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    # One-to-many relationship with invoices
    invoices = relationship("Invoice", back_populates="batch")


# ------------------------
# Update your Invoice model
# ------------------------
Invoice.batch_id = Column(Integer, ForeignKey("batches.id"), nullable=True)
Invoice.batch = relationship("Batch", back_populates="invoices")


# ------------------------
# Pydantic Schemas
# ------------------------
class InvoiceBase(BaseModel):
    id: int
    invoice_number: Optional[str]

    class Config:
        orm_mode = True


class BatchBase(BaseModel):
    name: str
    locked: Optional[bool] = False


class BatchCreate(BatchBase):
    invoice_ids: List[int] = []


class BatchRead(BatchBase):
    id: int
    invoices: List[InvoiceBase] = []

    class Config:
        orm_mode = True
