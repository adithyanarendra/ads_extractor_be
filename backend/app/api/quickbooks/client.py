import os
import asyncio
from time import time
from dotenv import load_dotenv
from intuitlib.client import AuthClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from .models import QuickBooksToken

load_dotenv()

CLIENT_ID = os.getenv("QUICKBOOKS_CLIENT_ID")
CLIENT_SECRET = os.getenv("QUICKBOOKS_CLIENT_SECRET")
REDIRECT_URI = os.getenv("QUICKBOOKS_REDIRECT_URI")
ENVIRONMENT = os.getenv("QUICKBOOKS_ENVIRONMENT", "sandbox")

auth_client = AuthClient(
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
    environment=ENVIRONMENT,
    redirect_uri=REDIRECT_URI,
)

async def save_qb_tokens(
    db: AsyncSession,
    org_id: int,
    access_token: str,
    refresh_token: str,
    realm_id: str,
    expires_in: int,
) -> None:

    expires_at = int(time()) + int(expires_in)

    result = await db.execute(
        select(QuickBooksToken).where(QuickBooksToken.org_id == org_id)
    )
    token_record = result.scalar_one_or_none()

    if token_record:
        token_record.access_token = access_token
        token_record.refresh_token = refresh_token
        token_record.realm_id = realm_id
        token_record.expires_at = expires_at
    else:
        token_record = QuickBooksToken(
            org_id=org_id,
            access_token=access_token,
            refresh_token=refresh_token,
            realm_id=realm_id,
            expires_at=expires_at,
        )
        db.add(token_record)

    await db.commit()
    await db.refresh(token_record)


async def load_qb_tokens(db: AsyncSession, org_id: int) -> QuickBooksToken | None:
    result = await db.execute(
        select(QuickBooksToken).where(QuickBooksToken.org_id == org_id)
    )
    return result.scalar_one_or_none()


async def get_valid_access_token(
    db: AsyncSession, org_id: int
) -> tuple[str | None, str | None]:
    token_record = await load_qb_tokens(db, org_id)
    if not token_record:
        return None, None

    if time() > token_record.expires_at - 60:
        try:
            await asyncio.to_thread(auth_client.refresh, token_record.refresh_token)

            await save_qb_tokens(
                db=db,
                org_id=org_id,
                access_token=auth_client.access_token,
                refresh_token=auth_client.refresh_token,
                realm_id=token_record.realm_id,
                expires_in=auth_client.expires_in,
            )

            return auth_client.access_token, token_record.realm_id
        except Exception as e:
            print("QuickBooks token refresh failed:", e)
            return None, None

    return token_record.access_token, token_record.realm_id


async def delete_qb_tokens(db: AsyncSession, org_id: int) -> bool:
    result = await db.execute(
        select(QuickBooksToken).where(QuickBooksToken.org_id == org_id)
    )
    token_record = result.scalar_one_or_none()
    if not token_record:
        return False
    await db.delete(token_record)
    await db.commit()
    return True

def qb_base_url():
    return (
        "https://quickbooks.api.intuit.com"
        if ENVIRONMENT == "production"
        else "https://sandbox-quickbooks.api.intuit.com"
    )


def qb_headers(access_token: str):
    return {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
