import io
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from ..users import models as users_models
from app.core.auth import get_current_user, require_roles, UserRole
from app.core.database import get_db
from .schemas import BatchCreate, AddInvoicesPayload
from . import crud
from ..invoices import crud as invoices_crud
from app.api.accounting import crud as accounting_crud
from app.api.accounting.routes import get_connected_zoho_connection
from app.api.accounting.zoho_client import ZohoClient

router = APIRouter(prefix="/batches", tags=["Batches"])


@router.get("/all")
async def get_all_batches(
    db: AsyncSession = Depends(get_db),
    current_user: users_models.User = Depends(get_current_user),
):
    res = await crud.list_batches(db, owner_id=current_user.effective_user_id)
    return res


@router.get("/{batch_id}")
async def get_batch_invoice_ids(
    batch_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: users_models.User = Depends(get_current_user),
):
    res = await crud.get_invoice_ids_for_batch(
        db, batch_id, owner_id=current_user.effective_user_id
    )
    if not res.get("ok"):
        raise HTTPException(status_code=404, detail=res.get("message"))
    return res


@router.get("/{batch_id}/invoices")
async def get_batch_invoices(
    batch_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: users_models.User = Depends(get_current_user),
):
    batch = await crud.get_batch_with_invoices(
        db, batch_id, owner_id=current_user.effective_user_id
    )
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    invoices = await crud.get_invoices_with_coas_for_batch(
        db, batch_id, owner_id=current_user.effective_user_id
    )
    return {"ok": True, "batch_id": batch_id, "invoices": invoices}


@router.post("/add")
async def add_batch(
    payload: BatchCreate,
    db: AsyncSession = Depends(get_db),
    current_user: users_models.User = Depends(get_current_user),
):
    res = await crud.create_batch(
        db,
        payload.name,
        owner_id=current_user.effective_user_id,
        invoice_ids=getattr(payload, "invoice_ids", None),
    )
    return res


@router.post("/add-child/{parent_id}")
async def add_child_batch(
    parent_id: int,
    payload: BatchCreate,
    db: AsyncSession = Depends(get_db),
    current_user: users_models.User = Depends(get_current_user),
):
    res = await crud.create_batch(
        db,
        payload.name,
        owner_id=current_user.effective_user_id,
        invoice_ids=getattr(payload, "invoice_ids", None),
        parent_id=parent_id,
    )
    return res


@router.post("/add/{batch_id}")
async def add_invoices(
    batch_id: int,
    payload: AddInvoicesPayload,
    db: AsyncSession = Depends(get_db),
    current_user: users_models.User = Depends(get_current_user),
):
    res = await crud.add_invoices_to_batch(
        db, batch_id, payload.invoice_ids, owner_id=current_user.effective_user_id
    )
    return res


@router.post("/lock/{batch_id}")
async def toggle_lock(
    batch_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: users_models.User = Depends(get_current_user),
):
    res = await crud.toggle_lock(db, batch_id, owner_id=current_user.effective_user_id)
    return res


@router.delete("/batch/{batch_id}")
async def delete_batch(
    batch_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: users_models.User = Depends(get_current_user),
):
    res = await crud.delete_batch_if_unlocked(
        db, batch_id, owner_id=current_user.effective_user_id
    )
    return res


@router.get("/download-zip/{batch_id}")
async def download_batch_zip(
    batch_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: users_models.User = Depends(get_current_user),
):
    try:
        zip_buffer, batch_name = await crud.generate_batch_zip_with_csv(
            db, batch_id, current_user.effective_user_id
        )
        zip_size = zip_buffer.getbuffer().nbytes
        return StreamingResponse(
            zip_buffer,
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{batch_name}.zip"',
                "Content-Length": str(zip_size),
            },
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/download-excel/{batch_id}")
async def download_batch_excel(
    batch_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: users_models.User = Depends(get_current_user),
):
    try:
        csv_buffer, batch_name = await crud.generate_batch_csv(
            db, batch_id, current_user.effective_user_id
        )
        csv_bytes = csv_buffer.getvalue().encode("utf-8")
        return StreamingResponse(
            io.BytesIO(csv_bytes),
            media_type="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="{batch_name}_summary.csv"',
                "Content-Length": str(len(csv_bytes)),
            },
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/download-images/{batch_id}")
async def download_batch_images(
    batch_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: users_models.User = Depends(get_current_user),
):
    try:
        zip_buffer, batch_name = await crud.generate_batch_images_zip(
            db, batch_id, current_user.effective_user_id
        )
        zip_size = zip_buffer.getbuffer().nbytes
        return StreamingResponse(
            zip_buffer,
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{batch_name}_images.zip"',
                "Content-Length": str(zip_size),
            },
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/{batch_id}/invoice/{invoice_id}")
async def delete_invoice_from_batch(
    batch_id: int,
    invoice_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: users_models.User = Depends(get_current_user),
):
    res = await crud.remove_invoice_from_batch(
        db, batch_id, invoice_id, owner_id=current_user.effective_user_id
    )
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=res.get("message"))
    return res


@router.delete("/{batch_id}/reset")
async def reset_batch(
    batch_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: users_models.User = Depends(get_current_user),
):
    res = await crud.clear_all_invoices_from_batch(
        db, batch_id, owner_id=current_user.effective_user_id
    )
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=res.get("message"))
    return res


@router.post("/{batch_id}/push-zoho")
async def push_batch_to_zoho(
    batch_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: users_models.User = Depends(get_current_user),
):
    if not (
        current_user.is_admin
        or getattr(current_user, "jwt_is_super_admin", False)
        or getattr(current_user, "jwt_is_accountant", False)
    ):
        raise HTTPException(status_code=403, detail="Access denied")
    batch = await crud.get_batch_with_invoices(
        db, batch_id, owner_id=current_user.effective_user_id
    )
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    invoices = await crud.get_invoices_with_coas_for_batch(
        db, batch_id, owner_id=current_user.effective_user_id
    )
    if not invoices:
        raise HTTPException(status_code=400, detail="Batch has no invoices")

    missing_coa = [inv for inv in invoices if not inv.get("chart_of_account_id")]
    if missing_coa:
        return {
            "success": 0,
            "failed": len(missing_coa),
            "error": f"{len(missing_coa)} invoices missing Chart of Account selection",
        }

    conn = await get_connected_zoho_connection(db, current_user)

    client = ZohoClient(conn.access_token, conn.external_org_id)
    summary = {"success": 0, "failed": 0, "errors": []}

    for inv in invoices:
        invoice_type = "sales" if inv.get("type") == "sales" else "expense"
        inv_id = inv.get("id")
        if inv_id:
            db_inv = await invoices_crud.get_invoice_by_id_and_owner(
                db, inv_id, current_user.effective_user_id
            )
            if db_inv:
                inv["trn_vat_number"] = db_inv.trn_vat_number
                inv["tax_amount"] = db_inv.tax_amount
                inv["before_tax_amount"] = db_inv.before_tax_amount
                inv["line_items"] = db_inv.line_items
        payload = {
            "invoices": [inv],
            "account_id": inv["chart_of_account_id"],
            "invoice_type": invoice_type,
        }
        result = await client.push_multiple_invoices(payload, db)

        if isinstance(result, dict) and result.get("success", 0) >= 1:
            summary["success"] += 1
            try:
                await invoices_crud.update_invoice_review(
                    db, inv.get("id"), current_user.effective_user_id, True
                )
                await invoices_crud.mark_invoice_as_published(db, inv.get("id"))
            except Exception:
                pass
        else:
            summary["failed"] += 1
            msg = ""
            if isinstance(result, dict):
                msg = result.get("message") or str(result)
            else:
                msg = str(result)
            summary["errors"].append(
                f"Invoice {inv.get('invoice_number') or inv.get('id')}: {msg}"
            )

    return summary
