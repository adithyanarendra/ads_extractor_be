import os
import time
import asyncio
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from datetime import datetime
import httpx
from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from intuitlib.enums import Scopes
from app.core import auth
from app.core.database import get_db
from app.api.invoices.crud import get_invoice_by_id, update_invoice_qb_id
from app.api.batches.crud import get_invoice_ids_for_batch
from app.api.quickbooks.client import (
    auth_client,
    save_qb_tokens,
    get_valid_access_token,
    delete_qb_tokens,
    ENVIRONMENT,
)
from app.core.database import async_session_maker
from app.api.batches import crud as batches_crud

router = APIRouter(prefix="/quickbooks", tags=["QuickBooks"])

FRONTEND_REDIRECT_URL = os.getenv("FRONTEND_REDIRECT_URL", "http://localhost:3000")

_COA_CACHE = {"ts": 0, "accounts": []}
CACHE_TTL = 300
MINOR_VERSION = 65
QB_TIMEOUT = 30

def _qb_base_url():
    return "https://quickbooks.api.intuit.com" if ENVIRONMENT == "production" else "https://sandbox-quickbooks.api.intuit.com"


def _qb_headers(access_token: str):
    return {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

async def find_qb_customer_by_name(client: httpx.AsyncClient, base_url: str, realm_id: str, name: str):
    if not name:
        return None
    safe_name = name.replace("'", "''") 
    
    q = f"select * from Customer where DisplayName = '{safe_name}'"
    url = f"{base_url}/v3/company/{realm_id}/query"
    resp = await client.get(url, params={"query": q})
    resp.raise_for_status()
    data = resp.json()
    customers = data.get("QueryResponse", {}).get("Customer", [])
    return customers[0] if customers else None


async def create_qb_customer(client: httpx.AsyncClient, base_url: str, realm_id: str, name: str, email: str = None):
    payload = {"DisplayName": name}
    if email:
        payload["PrimaryEmailAddr"] = {"Address": email}
    url = f"{base_url}/v3/company/{realm_id}/customer?minorversion={MINOR_VERSION}"
    resp = await client.post(url, json=payload)
    resp.raise_for_status()
    return resp.json().get("Customer")

import re
import httpx

async def get_or_create_vendor_in_qb(
    access_token: str,
    realm_id: str,
    vendor_name: str,
    vendor_email: str = None
):
    if not vendor_name:
        raise ValueError("vendor_name is required")

    clean_name = re.sub(r"[^\w\s\-\&]", "", vendor_name).strip()
    if not clean_name:
        raise ValueError(f"Vendor name '{vendor_name}' became empty after sanitization")

    safe_name = clean_name.replace("'", "''")

    base_url = _qb_base_url()
    headers = _qb_headers(access_token)

    async with httpx.AsyncClient(headers=headers, timeout=QB_TIMEOUT) as client:
        query = f"SELECT * FROM Vendor WHERE DisplayName = '{safe_name}'"
        query_url = f"{base_url}/v3/company/{realm_id}/query"

        resp = await client.get(query_url, params={"query": query})
        resp.raise_for_status()

        data = resp.json()
        vendors = data.get("QueryResponse", {}).get("Vendor", [])
        if vendors:
            return vendors[0].get("Id")

        vendor_payload = {"DisplayName": clean_name}
        if vendor_email:
            vendor_payload["PrimaryEmailAddr"] = {"Address": vendor_email}

        create_url = f"{base_url}/v3/company/{realm_id}/vendor?minorversion={MINOR_VERSION}"
        created_resp = await client.post(create_url, json=vendor_payload)
        created_resp.raise_for_status()

        return created_resp.json().get("Vendor", {}).get("Id")

@router.get("/status")
async def quickbooks_status(db: AsyncSession = Depends(get_db)):
    access_token, realm_id = await get_valid_access_token(db)
    return {"connected": bool(access_token), "realm_id": realm_id}

@router.get("/connect")
async def connect_quickbooks(request: Request):

    token = request.query_params.get("token")
    if not token:
        raise HTTPException(status_code=401, detail="Missing user token")

    base_url = await asyncio.to_thread(auth_client.get_authorization_url, [Scopes.ACCOUNTING])

    parts = list(urlparse(base_url))
    q = parse_qs(parts[4])
    q["state"] = token
    parts[4] = urlencode(q, doseq=True)
    final_url = urlunparse(parts)

    return RedirectResponse(url=final_url)

@router.get("/callback")
async def quickbooks_callback(request: Request, db: AsyncSession = Depends(get_db)):
    code = request.query_params.get("code")
    realm_id = request.query_params.get("realmId")
    token = request.query_params.get("state")
    redirect_url = f"{FRONTEND_REDIRECT_URL}?view=expense"

    if not code or not token:
        return RedirectResponse(url=f"{redirect_url}&error=missing_params")

    decoded = auth.decode_token(token)
    if not decoded.get("ok"):
        return RedirectResponse(url=f"{redirect_url}&error=invalid_token")

    await asyncio.to_thread(auth_client.get_bearer_token, code, realm_id)

    await save_qb_tokens(
        db=db,
        access_token=auth_client.access_token,
        refresh_token=auth_client.refresh_token,
        realm_id=realm_id,
        expires_in=auth_client.expires_in,
    )

    return RedirectResponse(url=f"{redirect_url}&qb_connected=true")


@router.get("/check-auth")
async def check_auth(db: AsyncSession = Depends(get_db)):
    access_token, _ = await get_valid_access_token(db)
    return {"authorized": bool(access_token)}


@router.get("/chart-of-accounts")
async def fetch_chart_of_accounts(db: AsyncSession = Depends(get_db)):
    now = time.time()
    if now - _COA_CACHE["ts"] < CACHE_TTL:
        return {"accounts": _COA_CACHE["accounts"]}

    access_token, realm_id = await get_valid_access_token(db)
    if not access_token or not realm_id:
        raise HTTPException(status_code=401, detail="QuickBooks not connected")

    base_url = _qb_base_url()
    query_url = f"{base_url}/v3/company/{realm_id}/query"
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
    params = {"query": "select Id,Name,AccountType,AccountSubType,CurrentBalance from Account"}

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(query_url, headers=headers, params=params)
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise HTTPException(status_code=e.response.status_code, detail=str(e))

    accounts = resp.json().get("QueryResponse", {}).get("Account", [])
    normalized = [
        {
            "id": a["Id"],
            "name": a["Name"],
            "type": a.get("AccountType"),
            "sub_type": a.get("AccountSubType"),
            "balance": a.get("CurrentBalance"),
        }
        for a in accounts
    ]

    _COA_CACHE["ts"] = now
    _COA_CACHE["accounts"] = normalized
    return {"accounts": normalized}

@router.delete("/disconnect")
async def disconnect_quickbooks(db: AsyncSession = Depends(get_db)):
    deleted = await delete_qb_tokens(db)
    _COA_CACHE["ts"] = 0
    _COA_CACHE["accounts"] = []
    return {"message": "QuickBooks disconnected" if deleted else "No QuickBooks connection found"}

import traceback
import json

async def push_single_invoice_core(
    db: AsyncSession, 
    invoice_id: int, 
    chart_of_account_id: int, 
    access_token: str, 
    realm_id: str,
    from_batch: bool = False          
):
    try:
        invoice = await get_invoice_by_id(db, invoice_id)
        if not invoice:
            raise ValueError(f"Invoice {invoice_id} not found")
        if from_batch:
            chart_of_account_id = invoice.chart_of_account_id
            if not chart_of_account_id:
                raise ValueError(
                    f"Invoice {invoice_id} has no chart_of_account_id stored."
                )
        else:
            if not chart_of_account_id:
                raise ValueError("chart_of_account_id is required")

        fields = {
            "invoice_number": invoice.invoice_number,
            "invoice_date": invoice.invoice_date,
            "vendor_name": invoice.vendor_name,
            "vendor_email": getattr(invoice, "vendor_email", None),
            "before_tax_amount": float(invoice.before_tax_amount or 0),
            "tax_amount": float(invoice.tax_amount or 0),
            "total": float(invoice.total or 0),
            "remarks": invoice.remarks,
            "description": invoice.description,
            "line_items": invoice.line_items or []
        }

        qb_vendor_id = await get_or_create_vendor_in_qb(
            access_token, realm_id,
            fields["vendor_name"],
            fields["vendor_email"]
        )

        lines = []
        total_tax = 0.0

        for li in fields["line_items"]:
            amount = float(li.get("before_tax_amount") or li.get("amount") or 0)
            vat = float(li.get("tax_amount") or 0)
            total_tax += vat
            desc = li.get("description") or fields["description"] or ""

            lines.append({
                "Amount": round(amount, 2),
                "DetailType": "AccountBasedExpenseLineDetail",
                "Description": desc,
                "AccountBasedExpenseLineDetail": {
                    "AccountRef": {"value": str(chart_of_account_id)}
                }
            })

        qb_payload = {
            "VendorRef": {"value": str(qb_vendor_id)},
            "Line": lines,
            "CurrencyRef": {"value": "AED"},
            "TxnTaxDetail": (
                {"TxnTaxCodeRef": {"value": "TAX"}, "TotalTax": round(total_tax, 2)}
                if total_tax > 0 else None
            ),
            "PrivateNote": fields["remarks"] or f"Invoice {invoice.id} pushed as Bill"
        }

        qb_payload = {k: v for k, v in qb_payload.items() if v is not None}

        if fields["invoice_date"]:
            qb_payload["TxnDate"] = str(fields["invoice_date"])

        if fields["invoice_number"]:
            qb_payload["DocNumber"] = fields["invoice_number"]

        base_url = _qb_base_url()
        url = f"{base_url}/v3/company/{realm_id}/bill?minorversion={MINOR_VERSION}"

        async with httpx.AsyncClient(timeout=QB_TIMEOUT, headers=_qb_headers(access_token)) as client:
            resp = await client.post(url, json=qb_payload)

        if resp.status_code >= 400:
            raise ValueError(f"QB API Error: {resp.text}")

        qb_bill_id = resp.json().get("Bill", {}).get("Id")
        if not qb_bill_id:
            raise ValueError("QuickBooks did not return Bill ID")

        await update_invoice_qb_id(db, invoice_id, int(qb_bill_id))

        from app.api.invoices.crud import mark_invoice_as_published
        await mark_invoice_as_published(db, invoice_id)

        return qb_bill_id

    except Exception as e:
        traceback.print_exc()
        raise


@router.post("/push-invoice/{invoice_id}")
async def push_bill_to_quickbooks(
    invoice_id: int,
    body: dict,
    db: AsyncSession = Depends(get_db),
):
    chart_of_account_id = body.get("chart_of_account_id")
    chart_of_account_name = body.get("chart_of_account_name")

    if not chart_of_account_id:
        raise HTTPException(status_code=400, detail="Missing chart_of_account_id")
    
    AP_NAMES = ["Accounts Payable", "A/P"]
    if chart_of_account_name in AP_NAMES:
        raise HTTPException(status_code=400, detail="Invalid Chart of Account")

    access_token, realm_id = await get_valid_access_token(db)
    if not access_token or not realm_id:
        raise HTTPException(status_code=401, detail="QuickBooks not connected")

    try:
        qb_bill_id = await push_single_invoice_core(
            db, invoice_id, chart_of_account_id, access_token, realm_id
        )
        return {"success": True, "qb_bill_id": qb_bill_id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
import asyncio
from datetime import datetime
from ..users import models as users_models
from ..invoices.routes import get_current_user

@router.post("/push-batch/{batch_id}")
async def push_batch_to_quickbooks(
    batch_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: users_models.User = Depends(get_current_user),
):
    import asyncio
    from app.core.database import async_session_maker

    res = await get_invoice_ids_for_batch(db, batch_id, owner_id=current_user.id)
    if not res.get("ok"):
        raise HTTPException(status_code=404, detail=res.get("message"))

    invoice_ids = res["data"]["invoice_ids"]
    if not invoice_ids:
        return {
            "success_count": 0,
            "failure_count": 0,
            "details": [],
            "message": "No invoices found in this batch.",
            "ok": True,
        }

    access_token, realm_id = await get_valid_access_token(db)
    if not access_token or not realm_id:
        raise HTTPException(status_code=401, detail="QuickBooks not connected")

    results = {"success_count": 0, "failure_count": 0, "details": []}

    async def safe_push(inv_id):
        async with async_session_maker() as new_db:
            try:
                bill_id = await push_single_invoice_core(
                    new_db,
                    invoice_id=inv_id,
                    chart_of_account_id=None,   
                    access_token=access_token,
                    realm_id=realm_id,
                    from_batch=True,            
                )
                return {"invoice_id": inv_id, "status": "success", "qb_bill_id": bill_id}

            except Exception as e:
                return {"invoice_id": inv_id, "status": "failed", "error": str(e)}

    semaphore = asyncio.Semaphore(5)

    async def sem_task(inv_id):
        async with semaphore:
            return await safe_push(inv_id)

    tasks = [sem_task(inv_id) for inv_id in invoice_ids]
    batch_results = await asyncio.gather(*tasks)

    for r in batch_results:
        results["details"].append(r)
        if r["status"] == "success":
            results["success_count"] += 1
        else:
            results["failure_count"] += 1

    if results["failure_count"] == 0:
        results["message"] = f"Successfully pushed {results['success_count']} invoices to QuickBooks."
        results["ok"] = True
    else:
        results["message"] = (
            f"Batch completed with errors. "
            f"{results['success_count']} succeeded, {results['failure_count']} failed."
        )
        results["ok"] = False

    return results

@router.get("/batch-status/{batch_id}")
async def get_quickbooks_batch_status(
    batch_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: users_models.User = Depends(get_current_user),
):
    """
    Provides a summary of unpublished invoices in a batch for the 
    QuickBooks pre-push confirmation dialog, including COA status.
    """
    batch_details = await batches_crud.get_invoice_ids_for_batch(db, batch_id, owner_id=current_user.id)
    if not batch_details:
        raise HTTPException(status_code=404, detail="Batch not found")

    invoices_data = await batches_crud.get_invoices_for_qb_batch_status(
        db, 
        batch_id=batch_id, 
        owner_id=current_user.id
    )
    
    ready_count = 0
    missing_coa_count = 0
    
    processed_invoices = []
    
    for inv in invoices_data:
        is_ready = bool(inv["chart_of_account_id"])
        
        if is_ready:
            ready_count += 1
        else:
            missing_coa_count += 1
        
        processed_invoices.append({
            "id": inv["id"],
            "invoice_number": inv["invoice_number"],
            "vendor_name": inv["vendor_name"],
            "chart_of_account_id": inv["chart_of_account_id"],
            "chart_of_account_name": inv["chart_of_account_name"],
            "is_ready": is_ready,
        })

    return {
        "batch_name": getattr(batch_details, "name", "N/A"),
        "total_invoices_in_batch": len(invoices_data),
        "ready_count": ready_count,
        "missing_coa_count": missing_coa_count,
        "invoices": processed_invoices,
    }