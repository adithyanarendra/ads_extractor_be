from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, DateTime, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy import Column, String

from ...core.database import Base


class Report(Base):
    __tablename__ = "reports"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    report_name = Column(String, nullable=False)
    type = Column(String, nullable=False)
    file_path = Column(String, nullable=False)

    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    uploaded_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user = relationship("User", back_populates="reports")
