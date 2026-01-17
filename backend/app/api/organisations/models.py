from sqlalchemy import Column, Integer, String, Boolean
from app.core.database import Base


class Organisation(Base):
    __tablename__ = "organisations"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    subscription_status = Column(String(50), nullable=True)
    max_seats = Column(Integer, nullable=True, default=0)
    current_seats = Column(Integer, nullable=True, default=0)
    is_active = Column(Boolean, default=True, nullable=False)
    super_admin_id = Column(Integer, nullable=True)
