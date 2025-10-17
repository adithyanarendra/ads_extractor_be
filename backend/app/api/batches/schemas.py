from pydantic import BaseModel
from typing import Optional, List


class BatchCreate(BaseModel):
    name: str
    invoice_ids: Optional[List[int]] = None  # optional: attach invoices on create


class BatchOut(BaseModel):
    id: int
    name: str
    locked: bool


class ToggleOut(BaseModel):
    id: int
    locked: bool


class InvoiceFileInfo(BaseModel):
    id: int
    invoice_number: Optional[str] = None
    file_path: str


class DownloadFilesOut(BaseModel):
    batch_id: int
    batch_name: Optional[str] = None
    files: List[InvoiceFileInfo]
    count: int


class AddInvoicesPayload(BaseModel):
    invoice_ids: List[int]
