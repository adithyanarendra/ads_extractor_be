from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timezone
import os
from urllib.parse import quote_plus

from app.core.database import get_db
from app.api.accounting import crud
from app.api.accounting.models import AccountingConnection, ConnStatusEnum
from .zoho_client import ZohoClient
from .oauth_utils import ZohoOAuth
from app.core import auth
from app.api.users.crud import mark_zb_connected,mark_zb_disconnected
from app.core.auth import get_current_user
from app.api.users.models import User

router = APIRouter(prefix="/api/accounting", tags=["accounting"])

oauth = ZohoOAuth()

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


# ------------------------------------------------------------
# 1. CONNECT URL
# ------------------------------------------------------------
@router.get("/zoho/connect")
async def connect_zoho(state: str | None = None):
    """Redirect user to Zoho OAuth authorization page."""
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

        org_id = 1
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
async def get_chart_of_accounts(db: AsyncSession = Depends(get_db)):
    org_id = 1
    conn = await crud.get_connection(db, org_id)
    if not conn:
        raise HTTPException(401, "Not connected to Zoho")

    conn = await ensure_valid_token(db, conn)
    if not conn:
        raise HTTPException(401, "Token refresh failed")

    client = ZohoClient(conn.access_token, conn.external_org_id)
    data = client.get_chart_of_accounts()

    if isinstance(data, dict) and "error" in data:
        raise HTTPException(status_code=502, detail=data["error"])

    accounts = data.get("chartofaccounts", []) if isinstance(data, dict) else data
    return {"accounts": accounts}


# ------------------------------------------------------------
# 4. PUSH SINGLE INVOICE
# ------------------------------------------------------------
@router.post("/zoho/push-invoice")
async def push_invoice(invoice_data: dict, db: AsyncSession = Depends(get_db)):
    org_id = 1
    conn = await crud.get_connection(db, org_id)

    if not conn:
        raise HTTPException(401, "Not connected to Zoho")

    conn = await ensure_valid_token(db, conn)

    client = ZohoClient(conn.access_token, conn.external_org_id)
    return client.push_invoice(invoice_data)


# ------------------------------------------------------------
# 5. PUSH MULTIPLE INVOICES
# ------------------------------------------------------------
@router.post("/zoho/push-invoices")
async def push_invoices(payload: dict, db: AsyncSession = Depends(get_db)):
    """Push multiple invoices to Zoho Books"""
    org_id = 1
    conn = await crud.get_connection(db, org_id)

    if not conn:
        raise HTTPException(401, "Not connected to Zoho")

    conn = await ensure_valid_token(db, conn)

    client = ZohoClient(conn.access_token, conn.external_org_id)
    
    
    invoice_type = payload.get("invoice_type", "expense")
    payload["invoice_type"] = invoice_type
    
    return client.push_multiple_invoices(payload)


# ------------------------------------------------------------
# 6. STATUS
# ------------------------------------------------------------
@router.get("/zoho/status")
async def zoho_status(db: AsyncSession = Depends(get_db)):
    org_id = 1
    conn = await crud.get_connection(db, org_id)

    if not conn:
        return {"connected": False, "org_id": org_id}

    expires_at = conn.expires_at
    now = datetime.now(timezone.utc)
    token_valid = bool(expires_at and expires_at > now)
    is_connected = conn.status == ConnStatusEnum.connected

    return {
        "connected": is_connected,
        "org_id": conn.org_id,
        "connection_id": conn.id,
        "expires_at": expires_at,
        "token_valid": token_valid,
    }


# ------------------------------------------------------------
# 7. DISCONNECT
# ------------------------------------------------------------
@router.post("/zoho/disconnect")
async def zoho_disconnect(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    org_id = 1
    conn = await crud.get_connection(db, org_id)

    if not conn:
        raise HTTPException(status_code=400, detail="Not connected")

    await crud.delete_connection(db, conn.id)

    await mark_zb_disconnected(db, current_user.id)

    return {
        "success": True,
        "message": "Disconnected from Zoho Books"
    }