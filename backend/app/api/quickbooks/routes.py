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
from app.api.users import crud as users_crud
from app.core.database import get_db

from app.api.invoices.crud import get_invoice_by_id, update_invoice_qb_id

from app.api.quickbooks.client import (
    auth_client,
    save_qb_tokens,
    get_valid_access_token,
    delete_qb_tokens,
    ENVIRONMENT,
)

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


async def get_or_create_vendor_in_qb(access_token: str, realm_id: str, vendor_name: str, vendor_email: str = None):
    base_url = _qb_base_url()
    headers = _qb_headers(access_token)

    async with httpx.AsyncClient(headers=headers, timeout=QB_TIMEOUT) as client:

        safe_name = vendor_name.replace("'", "''")
        q = f"select * from Vendor where DisplayName = '{safe_name}'"
        url = f"{base_url}/v3/company/{realm_id}/query"

        resp = await client.get(url, params={"query": q})
        resp.raise_for_status()

        data = resp.json()
        vendors = data.get("QueryResponse", {}).get("Vendor", [])
        if vendors:
            return vendors[0]["Id"]

        vendor_payload = {
            "DisplayName": vendor_name,
            "PrimaryEmailAddr": {"Address": vendor_email} if vendor_email else None
        }

        create_url = f"{base_url}/v3/company/{realm_id}/vendor?minorversion={MINOR_VERSION}"
        created = await client.post(create_url, json=vendor_payload)
        created.raise_for_status()

        return created.json()["Vendor"]["Id"]


@router.get("/status")
async def quickbooks_status(db: AsyncSession = Depends(get_db)):
    access_token, realm_id = await get_valid_access_token(db)
    return {"connected": bool(access_token), "realm_id": realm_id}

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
        raise HTTPException(
            status_code=400,
            detail="Cannot use Accounts Payable as chart_of_account_id for line items. Use an Expense or Asset account."
        )

    access_token, realm_id = await get_valid_access_token(db)
    if not access_token or not realm_id:
        raise HTTPException(status_code=401, detail="QuickBooks not connected")

    invoice = await get_invoice_by_id(db, invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

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

    base_url = _qb_base_url()

    qb_vendor_id = await get_or_create_vendor_in_qb(
        access_token, realm_id,
        fields["vendor_name"],
        fields["vendor_email"]
    )

    lines = []
    total_tax = 0.0

    if fields["line_items"]:
        for li in fields["line_items"]:
            amount = float(li.get("before_tax_amount") or li.get("amount") or 0)
            desc = li.get("description") or fields["description"] or ""
            vat = float(li.get("tax_amount") or 0)
            total_tax += vat

            line = {
                "Amount": round(amount, 2),
                "DetailType": "AccountBasedExpenseLineDetail",
                "Description": desc,
                "AccountBasedExpenseLineDetail": {
                    "AccountRef": {"value": str(chart_of_account_id)}
                }
            }
            lines.append(line)
    else:
        amount = fields["before_tax_amount"]
        lines.append({
            "Amount": round(amount, 2),
            "DetailType": "AccountBasedExpenseLineDetail",
            "Description": fields["description"] or "",
            "AccountBasedExpenseLineDetail": {
                "AccountRef": {"value": str(chart_of_account_id)}
            }
        })

    txn_tax_detail = {
        "TxnTaxCodeRef": {"value": "TAX"},
        "TotalTax": round(total_tax, 2)
    }

    def normalize_qb_date(date_value):
        if not date_value:
            return None
        try:
            return datetime.strptime(str(date_value), "%d-%m-%Y").strftime("%Y-%m-%d")
        except:
            return str(date_value)

    qb_payload = {
        "VendorRef": {"value": str(qb_vendor_id)},
        "Line": lines,
        "CurrencyRef": {"value": "AED"},
        "TxnTaxDetail": txn_tax_detail if total_tax > 0 else None,
        "PrivateNote": fields["remarks"] or f"Invoice {invoice.id} pushed as Bill",
    }

    qb_payload = {k: v for k, v in qb_payload.items() if v is not None}

    if fields["invoice_date"]:
        normalized = normalize_qb_date(fields["invoice_date"])
        if normalized:
            qb_payload["TxnDate"] = normalized

    if fields["invoice_number"]:
        qb_payload["DocNumber"] = fields["invoice_number"]

    url = f"{base_url}/v3/company/{realm_id}/bill?minorversion={MINOR_VERSION}"

    async with httpx.AsyncClient(timeout=QB_TIMEOUT, headers=_qb_headers(access_token)) as client:
        resp = await client.post(url, json=qb_payload)

    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)

    qb_response = resp.json()
    qb_bill_id = qb_response.get("Bill", {}).get("Id")

    if not qb_bill_id:
        raise HTTPException(status_code=500, detail="QuickBooks did not return Bill ID")

    await update_invoice_qb_id(db, invoice_id, int(qb_bill_id))

    return {"success": True, "qb_bill_id": qb_bill_id}


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

    base_url = (
        "https://quickbooks.api.intuit.com"
        if ENVIRONMENT == "production"
        else "https://sandbox-quickbooks.api.intuit.com"
    )
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