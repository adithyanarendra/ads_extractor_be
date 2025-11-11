from sqlalchemy import (
    Column,
    Integer,
    String,
    Boolean,
    DateTime,
    ForeignKey,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from ...core.database import Base


class Batch(Base):
    __tablename__ = "batches"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String, nullable=False)
    locked = Column(Boolean, nullable=False, default=False)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    owner = relationship("User", back_populates="batches")

    invoices = relationship("Invoice", back_populates="batch")
    __table_args__ = (
        UniqueConstraint("owner_id", "name", name="uq_batches_owner_name"),
    )
    parent_id = Column(Integer, ForeignKey("batches.id"), nullable=True)
    parent = relationship("Batch", remote_side=[id], back_populates="children")
    children = relationship("Batch", back_populates="parent")
