from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.auth import get_current_user
from datetime import date
from typing import Optional

from app.api.invoices.crud import (
    get_internal_expense_analytics,
    get_internal_sales_analytics,
    get_qb_expense_analytics,
    get_zb_expense_analytics,
    get_qb_sales_analytics,      
    get_zb_sales_analytics,      
)

from app.api.analytics.schemas import (
    InternalExpenseAnalyticsResponse,
    InternalSalesAnalyticsResponse,
)

from app.api.invoices import crud as invoices_crud


# ✅ IMPORTANT: Prefix added here
router = APIRouter(
    prefix="/analytics",
    tags=["Analytics"],
)

# ─────────────────────────────────────────────
# Internal Expenses Analytics
# ─────────────────────────────────────────────
@router.get("/internal/expenses")
async def internal_expense_analytics(
    range: int = Query(30, enum=[30, 90, 180]),
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    return await get_internal_expense_analytics(
        db=db,
        owner_id=user.id,
        days=range,
        from_date=from_date,
        to_date=to_date,
    )



# ─────────────────────────────────────────────
# QuickBooks Expenses Analytics
# ─────────────────────────────────────────────
@router.get("/qb/expenses")
async def qb_expense_analytics(
    range: int = Query(30, enum=[30, 90, 180]),
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    return await get_qb_expense_analytics(
        db=db,
        owner_id=user.id,
        days=range,
        from_date=from_date,
        to_date=to_date,
    )

# ─────────────────────────────────────────────
# ZohoBooks Expenses Analytics
# ─────────────────────────────────────────────

@router.get("/zb/expenses")
async def zb_expense_analytics(
    range: int = Query(30, enum=[30, 90, 180]),
    db: AsyncSession = Depends(get_db),
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    user = Depends(get_current_user),
):
    return await get_zb_expense_analytics(
        db=db,
        owner_id=user.id,
        days=range,
        from_date=from_date,
        to_date=to_date,
    )


@router.get("/sales/unpaid")
async def get_unpaid_sales_invoices(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Fetch all unpaid sales invoices (accounts receivable)
    """

    invoices = await invoices_crud.list_unpaid_sales_invoices(
        db=db,
        owner_id=current_user.id,
    )

    return {
        "count": len(invoices),
        "invoices": invoices,
    }

@router.get(
    "/internal/sales",
    response_model=InternalSalesAnalyticsResponse,
)
async def internal_sales_analytics(
    range: int = Query(30, enum=[30, 90, 180]),
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    return await get_internal_sales_analytics(
        db=db,
        owner_id=user.id,
        days=range,
        from_date=from_date,
        to_date=to_date,
    )


@router.get("/zb/sales")
async def zb_sales_analytics(
    range: int = Query(30, enum=[30, 90, 180]),
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    return await get_zb_sales_analytics(
        db=db,
        owner_id=user.id,
        days=range,
        from_date=from_date,
        to_date=to_date,
    )


@router.get("/qb/sales")
async def qb_sales_analytics(
    range: int = Query(30, enum=[30, 90, 180]),
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    return await get_qb_sales_analytics(
        db=db,
        owner_id=user.id,
        days=range,
        from_date=from_date,
        to_date=to_date,
    )
