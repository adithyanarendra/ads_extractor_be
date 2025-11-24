from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timedelta
from app.api.accounting.models import AccountingConnection, ProviderEnum, ConnStatusEnum


# ------------------------------------------------------------
# GET CONNECTION (ASYNC)
# ------------------------------------------------------------
async def get_connection(db: AsyncSession, org_id: int, provider: ProviderEnum = ProviderEnum.zoho):
    stmt = (
        select(AccountingConnection)
        .where(
            AccountingConnection.org_id == org_id,
            AccountingConnection.provider == provider
        )
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


# ------------------------------------------------------------
# CREATE CONNECTION (ASYNC)
# ------------------------------------------------------------
async def create_connection(
    db: AsyncSession,
    org_id: int,
    access_token: str,
    refresh_token: str,
    external_org_id: str,
    dc_domain: str,
    expires_in: int,
):
    expires_at = datetime.utcnow() + timedelta(seconds=expires_in)

    conn = AccountingConnection(
        org_id=org_id,
        provider=ProviderEnum.zoho,
        access_token=access_token,
        refresh_token=refresh_token,
        external_org_id=external_org_id,
        dc_domain=dc_domain,
        expires_at=expires_at,
        status=ConnStatusEnum.connected,
    )

    db.add(conn)
    await db.commit()
    await db.refresh(conn)

    return conn


# ------------------------------------------------------------
# UPDATE TOKENS (ASYNC)
# ------------------------------------------------------------
async def update_connection_tokens(
    db: AsyncSession,
    conn: AccountingConnection,
    access_token: str,
    refresh_token: str,
    expires_in: int,
):
    conn.access_token = access_token
    conn.refresh_token = refresh_token
    conn.expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
    conn.status = ConnStatusEnum.connected

    await db.commit()
    await db.refresh(conn)

    return conn


# ------------------------------------------------------------
# DISCONNECT (ASYNC) - revoke tokens
# ------------------------------------------------------------
async def disconnect_connection(
    db: AsyncSession,
    conn: AccountingConnection,
):
    """Mark connection revoked and clear tokens."""
    conn.status = ConnStatusEnum.revoked
    conn.access_token = None
    conn.refresh_token = None
    conn.expires_at = None
    conn.error_message = None

    await db.commit()
    await db.refresh(conn)

    return conn


# ------------------------------------------------------------
# DELETE CONNECTION (ASYNC)
# ------------------------------------------------------------
async def delete_connection(db: AsyncSession, connection_id: int):
    conn = await db.get(AccountingConnection, connection_id)
    if conn:
        await db.delete(conn)
        await db.commit()
