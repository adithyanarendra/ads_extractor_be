from pydantic import BaseModel
from typing import Optional, Dict, List


class InvoiceBase(BaseModel):
    invoice_number: Optional[str] = None
    invoice_date: Optional[str] = None
    vendor_name: Optional[str] = None
    trn_vat_number: Optional[str] = None
    before_tax_amount: Optional[str] = None
    tax_amount: Optional[str] = None
    total: Optional[str] = None
    reviewed: Optional[bool] = False
    remarks: Optional[str] = None
    description: Optional[str] = None
    type: Optional[str] = None
    is_processing: Optional[bool] = False


class InvoiceOut(InvoiceBase):
    id: int
    file_path: str


class InvoiceListResponse(BaseModel):
    ok: bool
    invoices: List[InvoiceOut]

    class Config:
        orm_mode = True


class InvoiceIdFilePath(BaseModel):
    id: int
    file_path: str

    class Config:
        orm_mode = True


class InvoiceTBRListResponse(BaseModel):
    ok: bool
    invoices: List[InvoiceIdFilePath]

    class Config:
        orm_mode = True


class ReviewPayload(BaseModel):
    invoice_id: int
    reviewed: bool
    corrected_fields: Optional[Dict[str, Optional[str]]] = None


class EditInvoiceFields(BaseModel):
    corrected_fields: Dict[str, Optional[str]]
