from pydantic import BaseModel, Field
from typing import Optional, Dict, List, Any
from pydantic import validator
from datetime import datetime


def _normalize_to_ddmmyyyy(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    s = str(s).strip().replace("/", "-")
    for fmt in ("%d-%m-%Y", "%Y-%m-%d", "%m-%d-%Y"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.strftime("%d-%m-%Y")
        except ValueError:
            pass
    return s  

def _normalize_dates_in_dict(d: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(d, dict):
        return d
    out = dict(d)
    for k, v in list(out.items()):
        if isinstance(v, str) and (k == "invoice_date" or k.endswith("_date")):
            out[k] = _normalize_to_ddmmyyyy(v)
    return out


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
    line_items: Optional[List[Any]] = None
    extraction_status: Optional[str] = None
    has_tax_note: Optional[bool] = False
    tax_note_type: Optional[str] = None
    tax_note_amount: Optional[float] = None
    chart_of_account_id: Optional[str] = None
    chart_of_account_name: Optional[str] = None
    is_paid: Optional[bool] = False
    is_valid: Optional[bool] = True

    
    @validator("invoice_date", pre=True)
    def _norm_invoice_date(cls, v):
        return _normalize_to_ddmmyyyy(v)

    @validator("tax_note_amount", pre=True)
    def _norm_tax_note_amount(cls, v):
        if v in ("", None):
            return None
        try:
            return float(v)
        except Exception:
            return v


class InvoiceOut(InvoiceBase):
    id: int
    file_path: str


class InvoiceListResponse(BaseModel):
    ok: bool
    invoices: List[InvoiceOut]
    total_count: int

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

class InvoiceCoAUpdate(BaseModel):
    chart_of_account_id: Optional[str] = None
    chart_of_account_name: Optional[str] = None


class ReviewPayload(BaseModel):
    invoice_id: int
    reviewed: bool
    corrected_fields: Optional[Dict[str, Any]] = None

    @validator("corrected_fields", pre=True)
    def _norm_corrected_fields(cls, v):
        return _normalize_dates_in_dict(v)


class EditInvoiceFields(BaseModel):
    corrected_fields: Dict[str, Any]

    @validator("corrected_fields", pre=True)
    def _norm_edit_fields(cls, v):
        return _normalize_dates_in_dict(v)


class HashCheckRequest(BaseModel):
    file_hash: str = Field(
        ..., description="SHA-256 hash of the file to check for duplicates"
    )


class InvoiceDeleteRequest(BaseModel):
    invoice_ids: List[int]
