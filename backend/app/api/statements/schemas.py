from pydantic import BaseModel
from typing import Optional, List


class StatementItemOut(BaseModel):
    id: int
    transaction_date: Optional[str]
    description: Optional[str]
    transaction_type: Optional[str]
    amount: Optional[str]
    balance: Optional[str]

    class Config:
        from_attributes = True


class StatementOut(BaseModel):
    id: int
    owner_id: int
    statement_type: str

    file_name: Optional[str]
    file_url: Optional[str]
    uploaded_at: Optional[str]

    items: List[StatementItemOut] = []

    class Config:
        from_attributes = True


class StatementListOut(BaseModel):
    id: int
    owner_id: int
    statement_type: str
    file_name: Optional[str]
    file_url: Optional[str]
    uploaded_at: Optional[str]

    class Config:
        from_attributes = True
