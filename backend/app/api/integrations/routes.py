from fastapi import APIRouter, Depends
from app.core.auth import get_current_user_from_token as get_current_user
from app.api.users.models import User
from app.core.database import get_db
from sqlalchemy.ext.asyncio import AsyncSession
from pathlib import Path
import json
import time

router = APIRouter(prefix="/integrations", tags=["Integrations"])

QB_TOKENS_FILE = Path("C:/Users/hp/ads_extractor/qb_tokens.json")


@router.get("/ping")
async def ping():
    """Simple health check endpoint for integrations."""
    return {"status": "ok", "message": "Integration route working fine"}


def check_quickbooks_connection(user_id: int) -> bool:
    """Check if QuickBooks is connected for the user."""
    if QB_TOKENS_FILE.exists():
        try:
            data = json.loads(QB_TOKENS_FILE.read_text())
            if "access_token" in data and "expires_at" in data:
                if time.time() < data["expires_at"]:
                    return True
        except Exception:
            pass
    return False


def check_zoho_connection(user_id: int) -> bool:
    """Check if Zoho Books is connected (placeholder)."""
    return False  


@router.get("/status", response_model=None)
async def get_integration_status(
    user: User = Depends(get_current_user),
    db = Depends(get_db), 
):
    """Return connection status for all integrations."""
    integrations = [
        {
            "vendor": "quickbooks",
            "name": "QuickBooks (Intuit)",
            "connected": check_quickbooks_connection(user.id),
        },
        {
            "vendor": "zoho",
            "name": "Zoho Books",
            "connected": check_zoho_connection(user.id),
        },
    ]

    return dict(integrations=integrations)