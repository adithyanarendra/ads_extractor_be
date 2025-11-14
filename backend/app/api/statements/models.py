from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, func
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Statement(Base):
    __tablename__ = "statements"

    id = Column(Integer, primary_key=True, index=True)

    statement_type = Column(String(50), nullable=False)  # "bank", "credit_card"
    owner_id = Column(Integer, nullable=False, index=True)

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


class StatementItem(Base):
    __tablename__ = "statement_items"

    id = Column(Integer, primary_key=True, index=True)
    statement_id = Column(
        Integer,
        ForeignKey("statements.id", ondelete="CASCADE"),
        nullable=False,
    )
    transaction_date = Column(String(20))
    description = Column(String)
    transaction_type = Column(String(20))  # "credit" | "debit"
    amount = Column(String)
    balance = Column(String)

    transaction_type_detail = Column(String(50), nullable=True)
    from_account = Column(String(100), nullable=True)
    to_account = Column(String(100), nullable=True)
    remarks = Column(String(500), nullable=True)

    statement = relationship("Statement", back_populates="items")
