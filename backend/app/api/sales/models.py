from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    Boolean,
    ForeignKey,
    DateTime,
    Text,
)
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from ...core.database import Base


class SalesProduct(Base):
    __tablename__ = "sales_products"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))

    name = Column(String, nullable=False)
    unique_code = Column(String, nullable=False, index=True)
    cost_per_unit = Column(Float, nullable=True)
    vat_percentage = Column(Integer, nullable=True, default=0)
    without_vat = Column(Boolean, nullable=True)
    total_cost = Column(Float, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SalesCustomer(Base):
    __tablename__ = "sales_customers"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))

    name = Column(String, nullable=False)
    trn = Column(String, nullable=True)
    registered_address = Column(Text, nullable=True)

    logo_path = Column(String, nullable=True)
    logo_r2_key = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SalesInvoice(Base):
    __tablename__ = "sales_invoices"

    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))

    # Seller snapshot
    company_name = Column(String, nullable=False)
    company_name_arabic = Column(String, nullable=True)
    company_trn = Column(String, nullable=False)
    company_address = Column(Text, nullable=True)

    # Customer snapshot
    customer_id = Column(Integer, ForeignKey("sales_customers.id"), nullable=True)
    customer_name = Column(String, nullable=True)
    customer_trn = Column(String, nullable=True)

    invoice_number = Column(String, nullable=True)
    invoice_date = Column(DateTime(timezone=True), server_default=func.now())

    notes = Column(Text, nullable=True)
    discount = Column(Float, nullable=True)

    subtotal = Column(Float, nullable=False)
    total_vat = Column(Float, nullable=False)
    total = Column(Float, nullable=False)

    file_path = Column(String, nullable=True)
    file_type = Column(String, nullable=True)
    is_deleted = Column(Boolean, default=False)

    line_items = relationship(
        "SalesInvoiceLineItem", back_populates="invoice", cascade="all, delete-orphan"
    )


class SalesInvoiceLineItem(Base):
    __tablename__ = "sales_invoice_line_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    invoice_id = Column(Integer, ForeignKey("sales_invoices.id", ondelete="CASCADE"))
    product_id = Column(Integer, ForeignKey("sales_products.id"), nullable=True)
    name = Column(String, nullable=True)

    description = Column(String, nullable=True)
    quantity = Column(Float, nullable=False)
    unit_cost = Column(Float, nullable=False)
    vat_percentage = Column(Integer, nullable=False)

    discount = Column(Float, nullable=True)

    line_total = Column(Float, nullable=False)

    invoice = relationship("SalesInvoice", back_populates="line_items")
    product = relationship("SalesProduct")


class SalesInventoryItem(Base):
    __tablename__ = "sales_inventory_items"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    product_id = Column(Integer, ForeignKey("sales_products.id"), nullable=True)
    product_name = Column(String, nullable=False)
    unique_code = Column(String, nullable=False, index=True)
    cost_price = Column(Float, nullable=True)
    selling_price = Column(Float, nullable=True)
    quantity = Column(Float, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    product = relationship("SalesProduct")
