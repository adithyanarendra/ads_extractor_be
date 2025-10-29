from sqlalchemy import Column, Integer, ForeignKey, String, DateTime
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from ...core.database import Base


class UserDocs(Base):
    __tablename__ = "user_docs"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    file_name = Column(String, nullable=False)
    file_url = Column(String, nullable=False)
    expiry_date = Column(DateTime(timezone=True), nullable=True)

    uploaded_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user = relationship("User", back_populates="documents")
