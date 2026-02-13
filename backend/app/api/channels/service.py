import secrets
from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.api.channels import models, constants
from app.api.channels.policies import ensure_channel_writable


def generate_public_token() -> str:
    return secrets.token_urlsafe(constants.PUBLIC_TOKEN_BYTES)


async def create_channel(db: AsyncSession, sender_id: int, payload):
    token = generate_public_token()

    channel = models.Channel(
        sender_id=sender_id,
        public_token=token,
        receiver_name=payload.receiver_name,
        receiver_company=payload.receiver_company,
        receiver_email=payload.receiver_email,
        receiver_phone=payload.receiver_phone,
        status=constants.CHANNEL_STATUS_CREATED,
        expires_at=datetime.now(timezone.utc) + timedelta(days=30),
    )

    db.add(channel)
    await db.commit()
    await db.refresh(channel)
    return channel


async def get_channel_by_token(db: AsyncSession, token: str):
    result = await db.execute(
        select(models.Channel).where(models.Channel.public_token == token)
    )
    return result.scalar_one_or_none()


async def add_message(db, channel, sender_role, msg_type, payload):
    ensure_channel_writable(channel)

    message = models.ChannelMessage(
        channel_id=channel.id,
        sender_role=sender_role,
        type=msg_type,
        payload=payload,
    )
    db.add(message)

    if channel.status == constants.CHANNEL_STATUS_CREATED:
        channel.status = constants.CHANNEL_STATUS_ACTIVE
        channel.opened_at = datetime.now(timezone.utc)

    await db.commit()
    return message


async def close_channel(db, channel):
    channel.status = constants.CHANNEL_STATUS_CLOSED
    channel.closed_at = datetime.now(timezone.utc)
    await db.commit()
