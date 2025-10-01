from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, Text
from sqlalchemy.orm import relationship
from .database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)

    invoices = relationship("Invoice", back_populates="owner", cascade="all, delete-orphan")

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
