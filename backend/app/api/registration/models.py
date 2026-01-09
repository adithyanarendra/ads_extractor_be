from sqlalchemy import Column, Integer, String, Boolean, DateTime, Enum, ForeignKey
from sqlalchemy.sql import func
import enum
from app.core.database import Base


class RegistrationType(str, enum.Enum):
    TRN_FREEZONE = "TRN_FREEZONE"
    TRN_LLC = "TRN_LLC"
    TRN_SOLE = "TRN_SOLE"
    CT = "CT"


class RegistrationStatus(str, enum.Enum):
    PENDING = "PENDING"
    DOC_UPLOADED = "DOC_UPLOADED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class RegistrationUser(Base):
    __tablename__ = "registration_users"

    id = Column(Integer, primary_key=True)
    registration_type = Column(Enum(RegistrationType), nullable=False)
    status = Column(
        Enum(RegistrationStatus),
        nullable=False,
        server_default=RegistrationStatus.PENDING.value,
    )

    name = Column(String, nullable=False)
    phone = Column(String, nullable=False)
    confirmed = Column(Boolean, nullable=False)
    reject_reason = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())


class RegistrationUserDoc(Base):
    __tablename__ = "registration_user_docs"

    id = Column(Integer, primary_key=True)
    registration_user_id = Column(
        Integer,
        ForeignKey("registration_users.id", ondelete="CASCADE"),
        nullable=False,
    )
    doc_key = Column(String, nullable=False)
    file_url = Column(String, nullable=False)
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now())
