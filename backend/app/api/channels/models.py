import uuid
from sqlalchemy import (
    Column,
    String,
    DateTime,
    ForeignKey,
    Text,
    Integer,
    JSON,
)
from sqlalchemy.sql import func
from app.core.database import Base


class Channel(Base):
    __tablename__ = "channels"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    sender_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    public_token = Column(String, unique=True, nullable=False, index=True)

    receiver_name = Column(String, nullable=False)
    receiver_company = Column(String, nullable=True)
    receiver_email = Column(String, nullable=True)
    receiver_phone = Column(String, nullable=True)

    status = Column(String, nullable=False, index=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    opened_at = Column(DateTime(timezone=True), nullable=True)
    closed_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)


class ChannelMessage(Base):
    __tablename__ = "channel_messages"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    channel_id = Column(String, ForeignKey("channels.id", ondelete="CASCADE"))

    sender_role = Column(String, nullable=False)
    type = Column(String, nullable=False)

    payload = Column(JSON, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
