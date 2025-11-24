from pydantic import BaseModel
from typing import Optional, List

class AccountBase(BaseModel):
    id: str                       
    name: str                      
    type: Optional[str] = None     
    sub_type: Optional[str] = None 
    balance: Optional[float] = None

class ChartOfAccountsResponse(BaseModel):
    accounts: List[AccountBase]
