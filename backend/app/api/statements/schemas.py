from pydantic import BaseModel
from typing import Optional, List, Dict, Any


class StatementItemOut(BaseModel):
    id: int
    transaction_date: Optional[str]
    description: Optional[str]
    transaction_type: Optional[str]
    transaction_type_detail: Optional[str]
    remarks: Optional[str]
    from_account: Optional[str]
    to_account: Optional[str]
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
    transaction_id: Optional[str]
    transaction_date: Optional[str]
    description: Optional[str]
    transaction_type: Optional[str]
    transaction_type_detail: Optional[str]
    remarks: Optional[str]
    from_account: Optional[str]
    to_account: Optional[str]
    amount: Optional[str]
    balance: Optional[str]

    class Config:
        from_attributes = True


class StatementItemEditIn(BaseModel):
    transaction_type_detail: Optional[str] = None
    remarks: Optional[str] = None
    from_account: Optional[str] = None
    to_account: Optional[str] = None


class StatementItemUniversalEditIn(BaseModel):
    updates: Dict[str, Any]
