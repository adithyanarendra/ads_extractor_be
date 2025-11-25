from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from io import BytesIO

from ...core.database import get_db
from ..invoices.routes import get_current_user
from . import crud, schemas
from .templates import renderer

router = APIRouter(prefix="/sales", tags=["sales"])


@router.get("/items")
async def get_products(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    products = await crud.list_products(db, current_user.id)
    return {"ok": True, "message": "Fetched", "data": products}


@router.post("/items")
async def add_product(
    payload: list[schemas.ProductCreate],
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    try:
        result = await crud.add_product(db, current_user.id, payload)
        return {"ok": True, "message": "Product(s) created", "data": result}
    except Exception as e:
        return {"ok": False, "message": "Failed", "error": str(e)}


@router.patch("/items/{pid}")
async def edit_product(
    pid: int,
    payload: schemas.ProductEdit,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    p = await crud.edit_product(db, current_user.id, pid, payload)
    if not p:
        return {"ok": False, "message": "Not found"}
    return {"ok": True, "message": "Updated", "data": p}


@router.delete("/items/{pid}")
async def delete_product(
    pid: int, db=Depends(get_db), current_user=Depends(get_current_user)
):
    ok = await crud.delete_product(db, current_user.id, pid)
    return {"ok": ok, "message": "Deleted" if ok else "Not found"}


@router.get("/customers")
async def get_customers(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    customers = await crud.list_customers(db, current_user.id)
    return {"ok": True, "message": "Fetched", "data": customers}


@router.post("/customers")
async def add_customer(
    payload: list[schemas.CustomerCreate],
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    try:
        result = await crud.add_customer(db, current_user.id, payload)
        return {"ok": True, "message": "Customer(s) created", "data": result}
    except Exception as e:
        return {"ok": False, "message": "Failed", "error": str(e)}


@router.patch("/customers/{cid}")
async def edit_customer(
    cid: int,
    payload: schemas.CustomerEdit,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    c = await crud.edit_customer(db, current_user.id, cid, payload)
    if not c:
        return {"ok": False, "message": "Not found"}
    return {"ok": True, "message": "Updated", "data": c}


@router.delete("/customers/{cid}")
async def delete_customer(
    cid: int, db=Depends(get_db), current_user=Depends(get_current_user)
):
    ok = await crud.delete_customer(db, current_user.id, cid)
    return {"ok": ok, "message": "Deleted" if ok else "Not found"}


@router.post("/invoices")
async def create_sales_invoice(
    payload: schemas.SalesInvoiceCreate,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    inv = await crud.create_invoice(db, current_user.id, payload)
    if not inv:
        return {"ok": False, "message": "Missing seller company details"}
    return {"ok": True, "message": "Invoice created", "data": {"invoice_id": inv.id}}


@router.get("/invoices")
async def list_sales_invoices(
    db=Depends(get_db), current_user=Depends(get_current_user)
):
    invoices = await crud.list_invoices(db, current_user.id)
    return {"ok": True, "message": "Fetched", "data": invoices}


@router.delete("/invoices/{invoice_id}")
async def delete_sales_invoice(
    invoice_id: int, db=Depends(get_db), current_user=Depends(get_current_user)
):
    ok = await crud.delete_invoice(db, current_user.id, invoice_id)
    return {"ok": ok, "message": "Deleted" if ok else "Not found"}


@router.get("/inventory")
async def get_inventory(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    items = await crud.list_inventory(db, current_user.id)
    return {"ok": True, "message": "Fetched", "data": items}


@router.post("/inventory")
async def add_inventory_items(
    payload: list[schemas.InventoryItemCreate],
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Accepts an array of inventory items.
    For a single item, send `[item]` just like items/customers.
    """
    try:
        result = await crud.add_inventory_items(db, current_user.id, payload)
        return {
            "ok": True,
            "message": "Inventory item(s) added/updated",
            "data": result,
        }
    except Exception as e:
        return {"ok": False, "message": "Failed", "error": str(e)}


@router.patch("/inventory/{iid}")
async def update_inventory_item(
    iid: int,
    payload: schemas.InventoryItemEdit,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    inv = await crud.edit_inventory_item(db, current_user.id, iid, payload)
    if not inv:
        return {"ok": False, "message": "Not found"}
    return {"ok": True, "message": "Updated", "data": inv}


@router.post("/inventory/adjust")
async def adjust_inventory(
    payload: schemas.InventoryAdjust,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    updated = await crud.adjust_inventory_quantity(
        db, current_user.id, payload.product_id, payload.delta
    )

    if not updated:
        return {"ok": False, "message": "Item not found"}

    return {"ok": True, "message": "Quantity updated", "data": updated}


@router.post("/invoices/{invoice_id}/download/{invoice_type}")
async def download_invoice(
    invoice_id: int,
    invoice_type: str,
    payload: schemas.InvoiceDownloadOptions = None,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Download invoice in 3 types:
    - simple
    - detailed
    - thermal (with optional width)
    """

    invoice = await crud.get_invoice_with_items(db, current_user.id, invoice_id)
    if not invoice:
        return {"ok": False, "message": "Invoice not found"}

    invoice_type = invoice_type.lower()

    if invoice_type == "simple":
        pdf_bytes = await renderer.render_simple_invoice_pdf(invoice)

    elif invoice_type == "detailed":
        pdf_bytes = await renderer.render_detailed_invoice_pdf(invoice)

    elif invoice_type == "thermal":
        width = payload.thermal_width_mm if payload else 58
        pdf_bytes = await renderer.render_thermal_invoice_pdf(invoice, width)

    else:
        return {"ok": False, "message": "Invalid invoice type"}

    return StreamingResponse(
        BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename='invoice_{invoice_id}.pdf'"
        },
    )
