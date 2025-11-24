from sqlalchemy import Column, Integer, String, Text, TIMESTAMP
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import ENUM
from app.core.database import Base

class AccountingConnection(Base):
    __tablename__ = "accounting_connections"   # change if your table name is different

    id = Column(Integer, primary_key=True, index=True)
    org_id = Column(Integer, nullable=False)
    provider = Column(String, nullable=False)  # "quickbooks"
    external_org_id = Column(String, nullable=True)
    dc_domain = Column(String, nullable=True, default="accounts.zoho.com")
    realm_id = Column(String, nullable=True)
    access_token = Column(Text, nullable=True)
    refresh_token = Column(Text, nullable=True)
    token_type = Column(String, nullable=True)
    scope = Column(Text, nullable=True)
    expires_at = Column(TIMESTAMP(timezone=True), nullable=True)
    status = Column(String, nullable=False, default="connected")
    last_sync_at = Column(TIMESTAMP(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)
    created_by = Column(String, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    last_updated_by = Column(String, nullable=True)
    updated_at = Column(TIMESTAMP(timezone=True), nullable=True)
