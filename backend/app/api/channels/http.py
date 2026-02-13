from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from datetime import datetime, timezone
from uuid import uuid4
import os
import mimetypes
from fastapi.responses import StreamingResponse
from app.core.database import get_db
from app.core.auth import get_current_user
from app.api.channels import service, schemas, models
from app.api.channels.constants import (
    CHANNEL_STATUS_EXPIRED,
    CHANNEL_STATUS_CLOSED,
    MAX_UPLOAD_MB,
    MESSAGE_FILE,
    SENDER,
    RECEIVER,
)
from app.utils.r2 import upload_to_r2_bytes
from app.utils.r2 import get_file_from_r2


router = APIRouter(prefix="/channels", tags=["channels"])

ALLOWED_MIME_TYPES = {
    "application/pdf",
    "image/png",
    "image/jpeg",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".doc", ".docx"}


async def _read_and_validate_upload(file: UploadFile) -> tuple[bytes, str, str, int]:
    if not file:
        raise HTTPException(status_code=400, detail="No file uploaded")

    filename = file.filename or "upload"
    ext = os.path.splitext(filename)[1].lower()
    content_type = file.content_type or ""

    if content_type not in ALLOWED_MIME_TYPES and ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Invalid file type")

    content = await file.read()
    size = len(content)
    if size > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(
            status_code=400,
            detail=f"File too large (max {MAX_UPLOAD_MB} MB)",
        )

    if not content:
        raise HTTPException(status_code=400, detail="Empty file")

    mime = content_type or ""
    return content, filename, mime, size


async def _store_file_and_message(
    db: AsyncSession,
    channel: models.Channel,
    sender_role: str,
    file: UploadFile,
):
    content, filename, mime, size = await _read_and_validate_upload(file)
    ext = os.path.splitext(filename)[1].lower() or ""
    key = f"channels/{channel.id}/{uuid4().hex}{ext}"
    url = upload_to_r2_bytes(content, key)

    msg = await service.add_message(
        db,
        channel,
        sender_role,
        MESSAGE_FILE,
        {"name": filename, "url": url, "size": size, "mime": mime},
    )

    return msg


@router.post("", response_model=schemas.ChannelCreateResponse)
async def create_channel_endpoint(
    payload: schemas.ChannelCreateRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    channel = await service.create_channel(db, user.id, payload)

    return {
        "id": channel.id,
        "public_link": f"/c/{channel.public_token}",
    }


@router.get("")
async def list_channels(
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    result = await db.execute(
        select(models.Channel)
        .where(models.Channel.sender_id == user.id)
        .order_by(models.Channel.created_at.desc())
    )

    channels = result.scalars().all()

    return {
        "ok": True,
        "channels": [
            {
                "id": c.id,
                "receiver_name": c.receiver_name,
                "receiver_email": c.receiver_email,
                "status": c.status,
                "created_at": c.created_at.isoformat(),
                "public_link": f"/c/{c.public_token}",
            }
            for c in channels
        ],
    }


@router.get("/{channel_id}")
async def get_channel_for_sender(
    channel_id: str,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    result = await db.execute(
        select(models.Channel)
        .where(models.Channel.id == channel_id)
        .where(models.Channel.sender_id == user.id)
    )
    channel = result.scalar_one_or_none()

    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    return {
        "ok": True,
        "channel": {
            "id": channel.id,
            "status": channel.status,
            "receiver_name": channel.receiver_name,
            "receiver_company": channel.receiver_company,
            "can_write": channel.status
            not in (
                CHANNEL_STATUS_CLOSED,
                CHANNEL_STATUS_EXPIRED,
            ),
        },
    }


@router.get("/{channel_id}/messages")
async def list_messages_for_sender(
    channel_id: str,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    result = await db.execute(
        select(models.Channel)
        .where(models.Channel.id == channel_id)
        .where(models.Channel.sender_id == user.id)
    )
    channel = result.scalar_one_or_none()

    if not channel:
        raise HTTPException(status_code=404)

    result = await db.execute(
        select(models.ChannelMessage)
        .where(models.ChannelMessage.channel_id == channel.id)
        .order_by(models.ChannelMessage.created_at.asc())
    )

    messages = result.scalars().all()

    return {
        "ok": True,
        "messages": [
            {
                "id": m.id,
                "sender_role": m.sender_role,
                "type": m.type,
                "payload": m.payload,
                "created_at": m.created_at.isoformat(),
            }
            for m in messages
        ],
    }


@router.get("/c/{token}")
async def resolve_channel_by_token(
    token: str,
    db: AsyncSession = Depends(get_db),
):
    channel = await service.get_channel_by_token(db, token)

    if not channel:
        raise HTTPException(status_code=404, detail="Invalid or expired link")

    now = datetime.now(timezone.utc)

    if channel.expires_at and channel.expires_at < now:
        channel.status = CHANNEL_STATUS_EXPIRED
        await db.commit()

    return {
        "ok": True,
        "channel": {
            "id": channel.id,
            "status": channel.status,
            "receiver_name": channel.receiver_name,
            "receiver_company": channel.receiver_company,
            "can_write": channel.status
            not in (
                CHANNEL_STATUS_CLOSED,
                CHANNEL_STATUS_EXPIRED,
            ),
        },
    }


@router.get("/c/{token}/messages")
async def list_messages(token: str, db: AsyncSession = Depends(get_db)):
    channel = await service.get_channel_by_token(db, token)
    if not channel:
        raise HTTPException(status_code=404)

    result = await db.execute(
        select(models.ChannelMessage)
        .where(models.ChannelMessage.channel_id == channel.id)
        .order_by(models.ChannelMessage.created_at.asc())
    )

    messages = result.scalars().all()

    return {
        "ok": True,
        "messages": [
            {
                "id": m.id,
                "sender_role": m.sender_role,
                "type": m.type,
                "payload": m.payload,
                "created_at": m.created_at.isoformat(),
            }
            for m in messages
        ],
    }


@router.post("/{channel_id}/upload")
async def upload_file_sender(
    channel_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    result = await db.execute(
        select(models.Channel)
        .where(models.Channel.id == channel_id)
        .where(models.Channel.sender_id == user.id)
    )
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    msg = await _store_file_and_message(db, channel, SENDER, file)

    from app.api.channels.connection_manager import manager

    await manager.broadcast(
        channel.id,
        {
            "type": "message",
            "data": {
                "id": msg.id,
                "sender_role": msg.sender_role,
                "type": msg.type,
                "payload": msg.payload,
                "created_at": msg.created_at.isoformat() if msg.created_at else None,
            },
        },
    )

    return {"ok": True, "message": "File uploaded", "data": msg.id}


@router.post("/c/{token}/upload")
async def upload_file_receiver(
    token: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    channel = await service.get_channel_by_token(db, token)
    if not channel:
        raise HTTPException(status_code=404, detail="Invalid or expired link")

    msg = await _store_file_and_message(db, channel, RECEIVER, file)

    from app.api.channels.connection_manager import manager

    await manager.broadcast(
        channel.id,
        {
            "type": "message",
            "data": {
                "id": msg.id,
                "sender_role": msg.sender_role,
                "type": msg.type,
                "payload": msg.payload,
                "created_at": msg.created_at.isoformat() if msg.created_at else None,
            },
        },
    )

    return {"ok": True, "message": "File uploaded", "data": msg.id}


@router.get("/{channel_id}/files/{message_id}")
async def download_file_sender(
    channel_id: str,
    message_id: str,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    result = await db.execute(
        select(models.Channel)
        .where(models.Channel.id == channel_id)
        .where(models.Channel.sender_id == user.id)
    )
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    msg = await db.get(models.ChannelMessage, message_id)
    if not msg or msg.channel_id != channel.id or msg.type != MESSAGE_FILE:
        raise HTTPException(status_code=404, detail="File not found")

    file_url = msg.payload.get("url")
    filename = msg.payload.get("name") or "file"
    if not file_url or "r2.dev/" not in file_url:
        raise HTTPException(status_code=404, detail="File not found")

    key = file_url.split("r2.dev/")[-1]
    file_obj = get_file_from_r2(key)
    if not file_obj:
        raise HTTPException(status_code=404, detail="File not found")

    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "X-Content-Type-Options": "nosniff",
    }
    return StreamingResponse(
        file_obj,
        media_type="application/octet-stream",
        headers=headers,
    )


@router.get("/c/{token}/files/{message_id}")
async def download_file_receiver(
    token: str,
    message_id: str,
    db: AsyncSession = Depends(get_db),
):
    channel = await service.get_channel_by_token(db, token)
    if not channel:
        raise HTTPException(status_code=404, detail="Invalid or expired link")

    msg = await db.get(models.ChannelMessage, message_id)
    if not msg or msg.channel_id != channel.id or msg.type != MESSAGE_FILE:
        raise HTTPException(status_code=404, detail="File not found")

    file_url = msg.payload.get("url")
    filename = msg.payload.get("name") or "file"
    if not file_url or "r2.dev/" not in file_url:
        raise HTTPException(status_code=404, detail="File not found")

    key = file_url.split("r2.dev/")[-1]
    file_obj = get_file_from_r2(key)
    if not file_obj:
        raise HTTPException(status_code=404, detail="File not found")

    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "X-Content-Type-Options": "nosniff",
    }
    return StreamingResponse(
        file_obj,
        media_type="application/octet-stream",
        headers=headers,
    )
