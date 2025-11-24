from sqlalchemy import Column, Integer, String, BigInteger
from ...core.database import Base

class QuickBooksToken(Base):
    __tablename__ = "quickbooks_tokens"

    id = Column(Integer, primary_key=True, autoincrement=True)
    access_token = Column(String, nullable=False)
    refresh_token = Column(String, nullable=False)
    realm_id = Column(String, nullable=False)
    expires_at = Column(BigInteger, nullable=False)
