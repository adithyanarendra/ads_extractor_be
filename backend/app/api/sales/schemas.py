from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


class ProductCreate(BaseModel):
    name: str
    unique_code: str
    vat_percentage: Optional[int] = None
    without_vat: Optional[bool] = None


class ProductEdit(BaseModel):
    name: Optional[str] = None
    unique_code: Optional[str] = None
    vat_percentage: Optional[int] = None
    without_vat: Optional[bool] = None


class CustomerCreate(BaseModel):
    name: str
    trn: Optional[str]
    registered_address: Optional[str]


class CustomerEdit(BaseModel):
    name: Optional[str]
    trn: Optional[str]
    registered_address: Optional[str]


class SalesLineItemCreate(BaseModel):
    product_id: Optional[int]
    name: Optional[str] = None
    description: str = None
    quantity: float
    unit_cost: float
    vat_percentage: int
    discount: Optional[float] = None


class SalesInvoiceCreate(BaseModel):
    invoice_number: Optional[str]
    customer_id: Optional[int]
    customer_name: Optional[str]
    customer_trn: Optional[str]
    notes: Optional[str]

    discount: Optional[float] = None

    line_items: List[SalesLineItemCreate] = []
    total: Optional[float] = None

    seller_doc_id: Optional[int] = None

    manual_seller_company_en: Optional[str] = None
    manual_seller_company_ar: Optional[str] = None
    manual_seller_trn: Optional[str] = None
    manual_seller_address: Optional[str] = None


class SalesInvoiceEdit(BaseModel):
    corrected_fields: dict
    line_items: Optional[List[SalesLineItemCreate]] = None


class InventoryItemCreate(BaseModel):
    product_id: Optional[int] = None
    product_name: Optional[str] = None
    unique_code: str
    cost_price: Optional[float] = None
    selling_price: Optional[float] = None
    quantity: float


class InventoryItemEdit(BaseModel):
    product_id: Optional[int] = None
    product_name: Optional[str] = None
    unique_code: Optional[str] = None
    cost_price: Optional[float] = None
    selling_price: Optional[float] = None
    quantity: Optional[float] = None


class InventoryAdjust(BaseModel):
    product_id: int
    delta: float


class InvoiceDownloadOptions(BaseModel):
    thermal_width_mm: Optional[int] = 58


class SalesTermsUpdate(BaseModel):
    terms: Optional[str] = ""
