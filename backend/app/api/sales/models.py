from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    Boolean,
    ForeignKey,
    DateTime,
    Text,
    JSON,
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
    customer_code = Column(String, nullable=True, index=True)

    is_vat_registered = Column(Boolean, nullable=False, default=False)
    trn = Column(String, nullable=True)

    address_line_1 = Column(Text, nullable=False)
    city = Column(String, nullable=False)
    emirate = Column(String, nullable=False)
    country_code = Column(String, nullable=False, default="AE")
    postal_code = Column(String, nullable=True)

    registered_address = Column(Text, nullable=True)

    email = Column(String, nullable=True)
    phone = Column(String, nullable=True)

    peppol_participant_id = Column(String, nullable=True)
    external_ref = Column(String, nullable=True)

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

    # seller
    company_name = Column(String, nullable=False)
    company_name_arabic = Column(String, nullable=True)
    company_trn = Column(String, nullable=False)
    company_address = Column(Text, nullable=True)

    # buyer
    customer_id = Column(
        Integer, ForeignKey("sales_customers.id", ondelete="SET NULL"), nullable=True
    )
    customer_name = Column(String, nullable=True)
    customer_trn = Column(String, nullable=True)

    # invoice dets
    invoice_number = Column(String, nullable=True)
    currency = Column(String, nullable=False, default="AED")
    invoice_type = Column(String, nullable=False, default="TAX_INVOICE")
    invoice_date = Column(DateTime(timezone=True), server_default=func.now())
    supply_date = Column(DateTime(timezone=True), nullable=False)
    due_date = Column(DateTime(timezone=True), nullable=True)

    # content
    notes = Column(Text, nullable=True)
    terms_and_conditions = Column(Text, nullable=True)
    discount = Column(Float, nullable=True)

    # tax summary
    tax_summary = Column(JSON, nullable=False)
    subtotal = Column(Float, nullable=False)
    total_vat = Column(Float, nullable=False)
    total = Column(Float, nullable=False)

    # payments
    amount_paid = Column(Float, nullable=False, default=0)
    last_payment_at = Column(DateTime(timezone=True), nullable=True)
    payment_events = Column(JSON, nullable=True)

    # meta
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
    product_id = Column(
        Integer, ForeignKey("sales_products.id", ondelete="SET NULL"), nullable=True
    )
    name = Column(String, nullable=True)

    description = Column(String, nullable=True)
    quantity = Column(Float, nullable=False)
    unit_cost = Column(Float, nullable=False)
    vat_percentage = Column(Integer, nullable=False)

    discount = Column(Float, nullable=True)

    line_total = Column(Float, nullable=False)

    invoice = relationship("SalesInvoice", back_populates="line_items")
    product = relationship("SalesProduct", passive_deletes=True)


class SalesInventoryItem(Base):
    __tablename__ = "sales_inventory_items"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    product_id = Column(
        Integer, ForeignKey("sales_products.id", ondelete="SET NULL"), nullable=True
    )
    product_name = Column(String, nullable=False)
    unique_code = Column(String, nullable=False, index=True)
    cost_price = Column(Float, nullable=True)
    selling_price = Column(Float, nullable=True)
    quantity = Column(Float, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    product = relationship("SalesProduct", passive_deletes=True)


class SalesTerms(Base):
    __tablename__ = "sales_terms"

    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    terms = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SalesTaxCreditNote(Base):
    __tablename__ = "sales_tax_credit_notes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))

    reference_invoice_id = Column(
        Integer, ForeignKey("sales_invoices.id", ondelete="SET NULL"), nullable=True
    )

    credit_note_number = Column(String, nullable=False, index=True)
    credit_note_date = Column(DateTime(timezone=True), server_default=func.now())

    customer_name = Column(String, nullable=True)
    customer_trn = Column(String, nullable=True)

    notes = Column(Text, nullable=True)

    subtotal = Column(Float, nullable=False)
    total_vat = Column(Float, nullable=False)
    total = Column(Float, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    reference_invoice = relationship("SalesInvoice", passive_deletes=True)
    line_items = relationship(
        "SalesTaxCreditNoteLineItem",
        back_populates="credit_note",
        cascade="all, delete-orphan",
    )


class SalesTaxCreditNoteLineItem(Base):
    __tablename__ = "sales_tax_credit_note_line_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    credit_note_id = Column(
        Integer, ForeignKey("sales_tax_credit_notes.id", ondelete="CASCADE")
    )

    product_id = Column(
        Integer, ForeignKey("sales_products.id", ondelete="SET NULL"), nullable=True
    )
    name = Column(String, nullable=True)

    description = Column(String, nullable=True)
    quantity = Column(Float, nullable=False)
    unit_cost = Column(Float, nullable=False)
    vat_percentage = Column(Integer, nullable=False)

    discount = Column(Float, nullable=True)
    line_total = Column(Float, nullable=False)

    credit_note = relationship("SalesTaxCreditNote", back_populates="line_items")
    product = relationship("SalesProduct", passive_deletes=True)
