from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession
from io import BytesIO

from ...core.database import get_db
from ..invoices.routes import get_current_user
from . import crud, schemas
from ..user_docs import schemas as user_docs_schemas
from ..user_docs import crud as user_docs_crud
from .templates import renderer
from .templates.renderer_escpos import render_invoice_escpos

router = APIRouter(prefix="/sales", tags=["sales"])


@router.get("/invoices/next-number")
async def get_next_invoice_number_api(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    number = await crud.get_next_invoice_number(db, current_user.effective_user_id)
    return {"ok": True, "data": number}


@router.get("/seller_profile")
async def get_seller_profile(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    profile = await user_docs_crud.get_or_create_seller_profile(
        db, current_user.effective_user_id
    )
    if not profile:
        return {"ok": True, "data": None}

    data = user_docs_schemas.SellerProfileOut.from_orm(profile).dict()
    return {"ok": True, "data": data}


@router.put("/seller_profile")
async def set_seller_profile(
    payload: user_docs_schemas.SellerProfileSelect,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    res = await user_docs_crud.set_seller_profile(
        db, current_user.effective_user_id, payload.doc_id
    )
    if not res.get("ok"):
        return {"ok": False, "error": res.get("error", "Update failed")}

    data = user_docs_schemas.SellerProfileOut.from_orm(res["data"]).dict()
    return {"ok": True, "data": data}

@router.get("/credit-notes/next-number")
async def get_next_credit_note_number_api(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    number = await crud.get_next_credit_note_number(db, current_user.effective_user_id)
    return {"ok": True, "data": number}


@router.get("/terms")
async def get_terms_api(
    db: AsyncSession = Depends(get_db), current_user=Depends(get_current_user)
):
    terms = await crud.get_terms(db, current_user.effective_user_id)
    return {"ok": True, "data": terms.terms if terms else ""}


@router.post("/terms")
async def update_terms_api(
    payload: schemas.SalesTermsUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    obj = await crud.update_terms(db, current_user.effective_user_id, payload)
    return {"ok": True, "message": "Updated", "data": obj.terms}


@router.get("/items")
async def get_products(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    products = await crud.list_products(db, current_user.effective_user_id)
    return {"ok": True, "message": "Fetched", "data": products}


@router.post("/items")
async def add_product(
    payload: list[schemas.ProductCreate],
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    try:
        result = await crud.add_product(db, current_user.effective_user_id, payload)
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
    p = await crud.edit_product(db, current_user.effective_user_id, pid, payload)
    if not p:
        return {"ok": False, "message": "Not found"}
    return {"ok": True, "message": "Updated", "data": p}


@router.delete("/items/{pid}")
async def delete_product(
    pid: int, db=Depends(get_db), current_user=Depends(get_current_user)
):
    ok = await crud.delete_product(db, current_user.effective_user_id, pid)
    return {"ok": ok, "message": "Deleted" if ok else "Not found"}


@router.get("/customers")
async def get_customers(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    customers = await crud.list_customers(db, current_user.effective_user_id)
    return {"ok": True, "message": "Fetched", "data": customers}


@router.post("/customers")
async def add_customer(
    payload: list[schemas.CustomerCreate],
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    try:
        result = await crud.add_customer(db, current_user.effective_user_id, payload)
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
    c = await crud.edit_customer(db, current_user.effective_user_id, cid, payload)
    if not c:
        return {"ok": False, "message": "Not found"}
    return {"ok": True, "message": "Updated", "data": c}


@router.delete("/customers/{cid}")
async def delete_customer(
    cid: int, db=Depends(get_db), current_user=Depends(get_current_user)
):
    ok = await crud.delete_customer(db, current_user.effective_user_id, cid)
    return {"ok": ok, "message": "Deleted" if ok else "Not found"}


@router.post("/invoices")
async def create_sales_invoice(
    payload: schemas.SalesInvoiceCreate,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    inv = await crud.create_invoice(db, current_user.effective_user_id, payload)
    if not inv:
        return {"ok": False, "message": "Missing seller company details"}
    return {"ok": True, "message": "Invoice created", "data": {"invoice_id": inv.id}}


@router.get("/invoices")
async def list_sales_invoices(
    db=Depends(get_db), current_user=Depends(get_current_user)
):
    invoices = await crud.list_invoices(db, current_user.effective_user_id)
    return {"ok": True, "message": "Fetched", "data": invoices}

@router.get("/credit-notes")
async def list_tax_credit_notes(
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    notes = await crud.list_tax_credit_notes(db, current_user.effective_user_id)
    return {"ok": True, "message": "Fetched", "data": notes}


@router.post("/invoices/{invoice_id}/credit-notes")
async def create_tax_credit_note(
    invoice_id: int,
    payload: schemas.TaxCreditNoteCreate,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    data, error = await crud.create_tax_credit_note(
        db, current_user.effective_user_id, invoice_id, payload
    )
    if data is None:
        return {"ok": False, "message": error or "Unable to create credit note"}

    return {"ok": True, "message": "Credit note created", "data": data}


@router.delete("/invoices/{invoice_id}")
async def delete_sales_invoice(
    invoice_id: int, db=Depends(get_db), current_user=Depends(get_current_user)
):
    ok = await crud.delete_invoice(db, current_user.effective_user_id, invoice_id)
    return {"ok": ok, "message": "Deleted" if ok else "Not found"}


@router.post("/invoices/{invoice_id}/payments")
async def record_sales_payment(
    invoice_id: int,
    payload: schemas.SalesPaymentCreate,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    data, error = await crud.record_payment(
        db, current_user.effective_user_id, invoice_id, payload
    )
    if data is None:
        return {"ok": False, "message": error or "Unable to record payment"}

    message = error or "Payment recorded"
    return {"ok": True, "message": message, "data": data}


@router.get("/inventory")
async def get_inventory(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    items = await crud.list_inventory(db, current_user.effective_user_id)
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
        result = await crud.add_inventory_items(
            db, current_user.effective_user_id, payload
        )
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
    inv = await crud.edit_inventory_item(
        db, current_user.effective_user_id, iid, payload
    )
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
        db, current_user.effective_user_id, payload.product_id, payload.delta
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
    invoice = await crud.get_invoice_with_items(
        db, current_user.effective_user_id, invoice_id
    )
    if not invoice:
        return {"ok": False, "message": "Invoice not found"}

    invoice_type = invoice_type.lower()

    if invoice_type == "simple":
        pdf_bytes = await renderer.render_simple_invoice_pdf(invoice, db)

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


@router.get("/invoices/{invoice_id}/print/thermal-escpos")
async def print_invoice_thermal_escpos(
    invoice_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    invoice = await crud.get_invoice_with_items(
        db, current_user.effective_user_id, invoice_id
    )

    if not invoice:
        return {"ok": False, "message": "Invoice not found"}

    escpos_bytes = render_invoice_escpos(invoice)

    return Response(
        content=escpos_bytes,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": (
                f'attachment; filename="invoice_{invoice_id}.escpos"'
            )
        },
    )
