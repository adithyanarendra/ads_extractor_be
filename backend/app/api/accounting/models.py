from sqlalchemy import (
    Column, Integer, String, Boolean, Text, DateTime, JSON, ForeignKey,
    Enum, Index, UniqueConstraint
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base
import enum

class ProviderEnum(str, enum.Enum):
    zoho = "zoho"
    quickbooks = "quickbooks"

class ConnStatusEnum(str, enum.Enum):
    connected = "connected"
    revoked = "revoked"
    error = "error"
    expired = "expired"

class AccountingConnection(Base):
    __tablename__ = "accounting_connections"

    id = Column(Integer, primary_key=True, index=True)
    
    
    org_id = Column(Integer, nullable=False, index=True)

    provider = Column(Enum(ProviderEnum), nullable=False)

    # Zoho
    external_org_id = Column(String(255), nullable=True)
    dc_domain = Column(String(100), nullable=True, default="accounts.zoho.com")
    #accounts_server = Column(String(255), nullable=False, default="https://accounts.zoho.com")


    # QuickBooks
    realm_id = Column(String(255), nullable=True)

    
    access_token = Column(Text, nullable=True)      
    refresh_token = Column(Text, nullable=True)     
    token_type = Column(String(50), nullable=True)
    scope = Column(Text, nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)

    status = Column(Enum(ConnStatusEnum), nullable=False, default=ConnStatusEnum.connected)
    last_sync_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)

    created_by = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_updated_by = Column(String(255), nullable=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    sync_logs = relationship(
        "ZohoSyncLog",
        back_populates="connection",
        passive_deletes=True
    )

    __table_args__ = (
        
        UniqueConstraint("org_id", "provider", name="uq_org_provider"),
        Index("ix_conn_org_provider", "org_id", "provider"),
    )

    def __repr__(self):
        return f"<AccountingConnection id={self.id} provider={self.provider} org_id={self.org_id}>"

class ZohoSyncLog(Base):
    __tablename__ = "zoho_sync_logs"

    id = Column(Integer, primary_key=True, index=True)
    org_id = Column(Integer, nullable=False, index=True)
    invoice_id = Column(Integer, nullable=True) 
    connection_id = Column(
        Integer,
        ForeignKey("accounting_connections.id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )

    sync_type = Column(String(50), nullable=True)  
    status = Column(String(50), nullable=False, index=True)  

    request_data = Column(JSON, nullable=True)    
    response_data = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)

    duration_ms = Column(Integer, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)

    connection = relationship("AccountingConnection", back_populates="sync_logs")

    __table_args__ = (
        Index("ix_log_org_status_created", "org_id", "status", "created_at"),
    )

    def __repr__(self):
        return f"<ZohoSyncLog id={self.id} status={self.status} invoice_id={self.invoice_id}>"
