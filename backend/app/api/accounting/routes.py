import requests
from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timezone
import os
from urllib.parse import quote_plus
from typing import List, Optional

from app.core.database import get_db
from app.api.accounting import crud
from app.api.accounting.models import AccountingConnection, ConnStatusEnum
from .zoho_client import ZohoClient
from .oauth_utils import ZohoOAuth
from app.core import auth
from app.api.users.crud import mark_zb_connected, mark_zb_disconnected
from app.core.auth import get_current_user
from app.core.enforcement import require_active_subscription
from app.api.users.models import User
from app.api.invoices import crud as invoices_crud

router = APIRouter(prefix="/api/accounting", tags=["accounting"])


def get_oauth():
    """Lazy-load oauth to ensure env vars are loaded first"""
    return ZohoOAuth()

# Frontend URL - read from environment, default to localhost:5173 for development
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173").rstrip("/")


def redirect_with_error(message: str):
    """Redirect helper that carries an error message back to the frontend."""
    encoded_message = quote_plus(message)
    return RedirectResponse(
        url=f"{FRONTEND_URL}/accounting?error={encoded_message}",
        status_code=302
    )


def redirect_with_success(connection_id: int):
    """Redirect helper that carries success message back to the frontend."""
    return RedirectResponse(
        url=f"{FRONTEND_URL}/accounting?success=true&connection_id={connection_id}",
        status_code=302
    )


# ------------------------------------------------------------
# HELPER: Ensure valid access token
# ------------------------------------------------------------
async def ensure_valid_token(db: AsyncSession, conn: AccountingConnection):
    """Refresh access token if expired."""
    now = datetime.now(timezone.utc)
    if conn.expires_at and conn.expires_at > now:
        return conn  
    oauth = get_oauth()
    token_response = oauth.refresh_access_token(
        refresh_token=conn.refresh_token,
        dc_domain=conn.dc_domain
    )
    
    if "error" in token_response:
        conn.status = "error"
        conn.error_message = token_response["error"]
        await db.commit()
        return None

    # Update DB
    await crud.update_connection_tokens(
        db=db,
        conn=conn,
        access_token=token_response["access_token"],
        refresh_token=token_response.get("refresh_token", conn.refresh_token),
        expires_in=token_response.get("expires_in", 3600),
    )

    return conn


def _fetch_organization_id(access_token: str, dc_domain: str) -> str | None:
    books_domain = dc_domain.replace("accounts.", "books.")
    url = f"{books_domain}/api/v3/organizations"
    headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}

    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        data = response.json()
        organizations = data.get("organizations") or data.get("data") or []
        if not organizations:
            return None
        return organizations[0].get("organization_id")
    except Exception as err:
        print("Unable to fetch Zoho organization_id:", err)
        return None


def _get_org_id_from_user(user: User):
    return getattr(user, "effective_user_id", user.id)


async def _fetch_zoho_connection(
    db: AsyncSession, current_user: User
) -> AccountingConnection | None:
    org_id = _get_org_id_from_user(current_user)
    conn = await crud.get_connection(db, org_id)
    return conn


async def get_connected_zoho_connection(
    db: AsyncSession, current_user: User
) -> AccountingConnection:
    conn = await _fetch_zoho_connection(db, current_user)
    if not conn:
        raise HTTPException(401, "Not connected to Zoho Books")
    conn = await ensure_valid_token(db, conn)
    if not conn:
        raise HTTPException(401, "Token refresh failed")
    return conn


# ------------------------------------------------------------
# 1. CONNECT URL
# ------------------------------------------------------------
@router.get("/zoho/connect")
async def connect_zoho(state: str | None = None):
    """Redirect user to Zoho OAuth authorization page."""
    oauth = get_oauth()  # Create fresh instance each time
    auth_url = oauth.get_auth_url(state=state)
    return RedirectResponse(url=auth_url)

# ------------------------------------------------------------
# 2. CALLBACK (OAuth Token Exchange)
# ------------------------------------------------------------

@router.get("/zoho/callback")
async def zoho_callback(
    request: Request,
    code: str = None,
    db: AsyncSession = Depends(get_db)
):
    try:
        token = request.query_params.get("state")
        if not token:
            return RedirectResponse(
                url=f"{FRONTEND_URL}/?zoho_error=Missing+user+token",
                status_code=302,
            )

        decoded = auth.decode_token(token)
        if not decoded.get("ok"):
            return RedirectResponse(
                url=f"{FRONTEND_URL}/?zoho_error=Invalid+token",
                status_code=302,
            )

        user_id = decoded["payload"].get("uid")
        if not user_id:
            return RedirectResponse(
                url=f"{FRONTEND_URL}/?zoho_error=Invalid+user",
                status_code=302,
            )

        if not code:
            return RedirectResponse(
                url=f"{FRONTEND_URL}/?zoho_error=Missing+authorization+code",
                status_code=302
            )

        dc_domain = request.query_params.get("accounts-server")
        if not dc_domain:
            return RedirectResponse(
                url=f"{FRONTEND_URL}/?zoho_error=Missing+accounts-server",
                status_code=302
            )
        oauth = get_oauth()
        token_response = await oauth.exchange_code_for_token(
            code=code,
            dc_domain=dc_domain
        )

        access_token = token_response.get("access_token")
        refresh_token = token_response.get("refresh_token")
        external_org_id = token_response.get("organization_id")
        expires_in = token_response.get("expires_in", 3600)

        if not access_token or not refresh_token:
            error_msg = token_response.get("error", "Unknown error")
            return RedirectResponse(
                url=f"{FRONTEND_URL}/?zoho_error={quote_plus(error_msg)}",
                status_code=302
            )

        fetched_org_id = _fetch_organization_id(access_token, dc_domain)
        if fetched_org_id:
            external_org_id = fetched_org_id

        acting_id = decoded["payload"].get("acting_user_id")
        org_id = acting_id or user_id
        existing = await crud.get_connection(db, org_id)

        if existing:
            conn = await crud.update_connection_tokens(
                db, existing, access_token, refresh_token, expires_in
            )
        else:
            conn = await crud.create_connection(
                db=db,
                org_id=org_id,
                access_token=access_token,
                refresh_token=refresh_token,
                external_org_id=external_org_id,
                dc_domain=dc_domain,
                expires_in=expires_in,
            )

        await mark_zb_connected(db, user_id)
        await invoices_crud.reset_invoices_on_software_switch(db, user_id, "zb")

        return RedirectResponse(
            url=f"{FRONTEND_URL}/?zoho_connected=true&connection_id={conn.id}",
            status_code=302
        )

    except Exception as e:
        return RedirectResponse(
            url=f"{FRONTEND_URL}/?zoho_error={quote_plus(str(e))}",
            status_code=302
        )


# ------------------------------------------------------------
# 3. CHART OF ACCOUNTS
# ------------------------------------------------------------
@router.get("/zoho/chart-of-accounts")
async def get_chart_of_accounts(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    conn = await get_connected_zoho_connection(db, current_user)
    client = ZohoClient(conn.access_token, conn.external_org_id)
    data = client.get_chart_of_accounts()

    if isinstance(data, dict) and "error" in data:
        raise HTTPException(status_code=502, detail=data["error"])

    accounts = data.get("chartofaccounts", []) if isinstance(data, dict) else data
    return {"accounts": accounts}


# ------------------------------------------------------------
# 4. PUSH SINGLE INVOICE
# ------------------------------------------------------------
    return client.push_invoice(invoice_data)


# ------------------------------------------------------------
# 5. PUSH MULTIPLE INVOICES
# ------------------------------------------------------------
async def mark_invoices_verified(
    db: AsyncSession,
    owner_id: int,
    details: Optional[List[dict]],
    chart_of_account_id: str | None = None,
    chart_of_account_name: str | None = None,
):
    if not details:
        return
    for detail in details:
        if detail.get("status") not in {"success", "duplicate"}:
            continue
        invoice_id = detail.get("invoice_id")
        if not invoice_id:
            continue
        try:
            corrected_fields = {}
            if chart_of_account_id:
                corrected_fields["chart_of_account_id"] = chart_of_account_id
            if chart_of_account_name:
                corrected_fields["chart_of_account_name"] = chart_of_account_name

            await invoices_crud.update_invoice_review(
                db,
                invoice_id,
                owner_id,
                True,
                corrected_fields if corrected_fields else None,
            )
            await invoices_crud.mark_invoice_as_published(db, invoice_id)
        except Exception:
            continue


@router.post("/zoho/push-invoices")
async def push_invoices(
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    """Push multiple invoices to Zoho Books"""
    conn = await get_connected_zoho_connection(db, current_user)
    client = ZohoClient(conn.access_token, conn.external_org_id)

    account_id = payload.get("account_id")
    account_name = payload.get("account_name")
    invoice_type = payload.get("invoice_type", "expense")
    payload["invoice_type"] = invoice_type

    invoice_ids = [
        inv.get("id") for inv in payload.get("invoices", []) if inv.get("id")
    ]

    if not invoice_ids:
        raise HTTPException(status_code=400, detail="No invoices selected")

    invoices_from_db = await invoices_crud.get_invoices_by_ids_and_owner(
        db, invoice_ids, current_user.effective_user_id
    )
    invoice_map = {inv.id: inv for inv in invoices_from_db}

    if len(invoice_map) != len(invoice_ids):
        missing_ids = [i for i in invoice_ids if i not in invoice_map]
        raise HTTPException(
            status_code=404,
            detail=f"Invoices not found or not owned by user: {missing_ids}",
        )

    not_verified = [inv.id for inv in invoices_from_db if not inv.reviewed]
    if not_verified:
        raise HTTPException(
            status_code=400,
            detail="Only verified invoices can be pushed",
        )

    if account_id:
        for invoice_id in invoice_ids:
            await invoices_crud.set_invoice_coa(
                db,
                invoice_id,
                current_user.effective_user_id,
                account_id,
                account_name,
            )
    else:
        missing_coa = [
            inv.id
            for inv in invoices_from_db
            if not inv.chart_of_account_id
        ]
        if missing_coa:
            raise HTTPException(
                status_code=400,
                detail="Selected invoices are missing Chart of Account. Please update and try again.",
            )

        enriched_invoices = []
        payload_invoices = payload.get("invoices", [])
        for invoice in payload_invoices:
            inv_id = invoice.get("id")
            if not inv_id:
                continue
            db_inv = invoice_map.get(inv_id)
            if not db_inv:
                continue
            enriched_invoices.append(
                {
                    **invoice,
                    "account_id": db_inv.chart_of_account_id,
                    "account_name": db_inv.chart_of_account_name,
                }
            )
        payload["invoices"] = enriched_invoices

    payload_invoices = payload.get("invoices", [])
    for invoice in payload_invoices:
        inv_id = invoice.get("id")
        if not inv_id:
            continue
        db_inv = invoice_map.get(inv_id)
        if not db_inv:
            continue
        invoice["trn_vat_number"] = db_inv.trn_vat_number
        invoice["tax_amount"] = db_inv.tax_amount
        invoice["before_tax_amount"] = db_inv.before_tax_amount
        invoice["line_items"] = db_inv.line_items

    result = await client.push_multiple_invoices(payload, db)

    await mark_invoices_verified(
        db,
        current_user.effective_user_id,
        result.get("details"),
        chart_of_account_id=account_id,
        chart_of_account_name=account_name,
    )

    return result

# ------------------------------------------------------------
# 6. STATUS
# ------------------------------------------------------------
@router.get("/zoho/status")
async def get_zoho_status(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    """Get Zoho Books connection status"""
    conn = await _fetch_zoho_connection(db, current_user)

    if not conn:
        return {
            "connected": False,
            "status": "disconnected",
            "org_id": None,
            "connection_id": None,
            "expires_at": None,
            "token_valid": False,
        }

    now = datetime.now(timezone.utc)
    token_valid = conn.expires_at and conn.expires_at > now
    expires_at = conn.expires_at.isoformat() if conn.expires_at else None
    is_connected = conn.status == ConnStatusEnum.connected

    return {
        "connected": is_connected,
        "status": conn.status.value if hasattr(conn.status, "value") else str(conn.status),
        "org_id": conn.org_id,
        "connection_id": conn.id,
        "expires_at": expires_at,
        "token_valid": token_valid,
        "organization_id": conn.external_org_id,
    }


# ------------------------------------------------------------
# 7. DISCONNECT
# ------------------------------------------------------------
@router.post("/zoho/disconnect")
async def disconnect_zoho(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    """Disconnect from Zoho Books"""
    conn = await _fetch_zoho_connection(db, current_user)

    if not conn:
        raise HTTPException(status_code=404, detail="No Zoho connection found")

    await crud.delete_connection(db, conn.id)
    await mark_zb_disconnected(db, current_user.id)

    return {
        "success": True,
        "message": "Disconnected from Zoho Books",
    }

@router.get("/zoho/simple-status")
async def zoho_simple_status(
    user: User = Depends(get_current_user),
):
    return {
        "connected": bool(user.is_zb_connected)
    }
