from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey, func
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Statement(Base):
    __tablename__ = "statements"

    id = Column(Integer, primary_key=True, index=True)

    statement_type = Column(String(50), nullable=False)  # "bank", "credit_card"
    owner_id = Column(Integer, nullable=False, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)

    file_name = Column(String(255))
    file_key = Column(String(255))
    file_url = Column(String(500))

    uploaded_at = Column(DateTime(timezone=True), server_default=func.now())

    items = relationship(
        "StatementItem",
        back_populates="statement",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    account = relationship("Account", back_populates="statements")


class StatementItem(Base):
    __tablename__ = "statement_items"

    id = Column(Integer, primary_key=True, index=True)
    statement_id = Column(
        Integer,
        ForeignKey("statements.id", ondelete="CASCADE"),
        nullable=False,
    )
    transaction_id = Column(String(200), nullable=True)
    transaction_date = Column(String(20))
    description = Column(String)
    transaction_type = Column(String(20))  # "credit" | "debit"
    amount = Column(String)
    balance = Column(String)

    transaction_type_detail = Column(String(50), nullable=True)
    from_account = Column(String(100), nullable=True)
    to_account = Column(String(100), nullable=True)
    remarks = Column(String(500), nullable=True)

    matched_invoice_id = Column(Integer, nullable=True)
    match_confidence = Column(Integer, nullable=True)
    match_reason = Column(String(255), nullable=True)
    is_matched = Column(Boolean, default=False)

    statement = relationship("Statement", back_populates="items")


class Account(Base):
    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, nullable=False, index=True)
    account_number = Column(String(100), nullable=False, index=True)
    provider = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    statements = relationship("Statement", back_populates="account", lazy="selectin")
