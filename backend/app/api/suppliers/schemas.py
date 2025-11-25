from pydantic import BaseModel
from typing import Optional, List, Any


class SupplierBase(BaseModel):
    name: str
    trn_vat_number: Optional[str] = None
    rules_extract_lines: Optional[bool] = False


class SupplierCreate(SupplierBase):
    pass


class SupplierUpdate(BaseModel):
    name: Optional[str] = None
    trn_vat_number: Optional[str] = None
    rules_extract_lines: Optional[bool] = None


class SupplierOut(SupplierBase):
    id: int
    normalized_name: str
    is_active: bool
    merged_into_id: Optional[int] = None
    invoice_count: int = 0

    class Config:
        orm_mode = True


class ApiResponse(BaseModel):
    ok: bool
    message: Optional[str] = None
    error: Optional[str] = None
    data: Optional[Any] = None


class SupplierListResponse(BaseModel):
    ok: bool
    message: Optional[str] = None
    error: Optional[str] = None
    data: Optional[List[SupplierOut]] = None
    total_count: Optional[int] = None


class MergeRequest(BaseModel):
    source_supplier_ids: List[int]
    target_supplier_id: int
