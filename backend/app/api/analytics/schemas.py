from pydantic import BaseModel
from typing import Optional


class TopVendorSchema(BaseModel):
    name: Optional[str]
    amount: float


class InternalExpenseAnalyticsResponse(BaseModel):
    range_days: int
    expense_count: int
    total_expenses: float
    vendors_count: int
    cost_due_today: float
    top_vendor: TopVendorSchema

class TopCustomerSchema(BaseModel):
    name: Optional[str]
    amount: float


class InternalSalesAnalyticsResponse(BaseModel):
    range_days: int
    sales_count: int
    total_sales: float
    customers_count: int
    amount_receivable: float
    top_customer: TopCustomerSchema