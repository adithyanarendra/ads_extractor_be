from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from ...core.database import Base
import re


def normalize_name(name: str) -> str:
    name = name.lower()
    name = re.sub(r"[^a-z0-9]", "", name)
    return name.strip()


class Supplier(Base):
    __tablename__ = "suppliers"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True)

    name = Column(String, nullable=False)
    normalized_name = Column(String, nullable=False, index=True)

    trn_vat_number = Column(String(20), nullable=True)

    rules_extract_lines = Column(Boolean, default=False)

    is_active = Column(Boolean, default=True)
    merged_into_id = Column(Integer, ForeignKey("suppliers.id"), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    invoices = relationship("Invoice", backref="supplier")
