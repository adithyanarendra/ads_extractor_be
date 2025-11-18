from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, DateTime, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from ...core.database import Base


class Company(Base):
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    contact_person = Column(String, nullable=True)
    email = Column(String, nullable=True)
    number = Column(String, nullable=True)
    address = Column(String, nullable=True)
    users_allowed = Column(JSON, default=[])

    created_by = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_updated_by = Column(String, nullable=True)
    last_updated_date = Column(DateTime(timezone=True), onupdate=func.now())
    users = relationship(
        "CompanyUser",
        back_populates="company",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class CompanyUser(Base):
    __tablename__ = "company_users"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    company_id = Column(
        Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    company_admin = Column(Boolean, default=False, nullable=False)

    added_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    added_at = Column(DateTime(timezone=True), server_default=func.now())

    company = relationship("Company", back_populates="users")
    user = relationship(
        "User",
        back_populates="companies_assoc",
        foreign_keys=[user_id],
    )
    added_by_user = relationship(
        "User",
        foreign_keys=[added_by],
    )
