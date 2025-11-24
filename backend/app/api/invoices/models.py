from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, DateTime, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from ...core.database import Base


class Invoice(Base):
    __tablename__ = "invoices"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    file_path = Column(String, nullable=False)
    invoice_number = Column(String, nullable=True)
    invoice_date = Column(String, nullable=True)
    vendor_name = Column(String, nullable=True)
    trn_vat_number = Column(String, nullable=True)
    before_tax_amount = Column(String, nullable=True)
    tax_amount = Column(String, nullable=True)
    total = Column(String, nullable=True)
    reviewed = Column(Boolean, default=False)
    remarks = Column(String, nullable=True)
    description = Column(String, nullable=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, index=True)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    type = Column(String(20), nullable=True)
    batch_id = Column(Integer, ForeignKey("batches.id"), nullable=True)
    batch = relationship("Batch", back_populates="invoices")
    owner = relationship("User", back_populates="invoices")
    company = relationship("Company", backref="invoices")
    file_hash = Column(String(64), nullable=False, index=True)
    is_duplicate = Column(Boolean, default=False, nullable=False)

    is_processing = Column(Boolean, default=False)
    line_items = Column(JSON, nullable=True)
    extraction_status = Column(String(20), nullable=True, default="pending")
    has_tax_note = Column(Boolean, default=False)
    tax_note_type = Column(String(20), nullable=True)
    tax_note_amount = Column(String, nullable=True)

    qb_id = Column(Integer, nullable=True)
    chart_of_account_id = Column(String, nullable=True)   
    chart_of_account_name = Column(String, nullable=True) 
