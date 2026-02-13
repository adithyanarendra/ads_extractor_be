from fastapi import HTTPException
from app.api.channels.constants import (
    CHANNEL_STATUS_CLOSED,
    CHANNEL_STATUS_EXPIRED,
)


def ensure_channel_writable(channel):
    if channel.status in (CHANNEL_STATUS_CLOSED, CHANNEL_STATUS_EXPIRED):
        raise HTTPException(status_code=403, detail="Channel is closed")
