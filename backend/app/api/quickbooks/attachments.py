import json
import mimetypes
import os
from typing import Optional, Tuple
from urllib.parse import urlparse

import httpx

from app.core.config import FILES_SERVICE_BASE_URL
from app.utils.files_service import get_file_from_files_service
from app.utils.r2 import get_file_from_r2


MAX_UPLOAD_BYTES = 100 * 1024 * 1024  # QBO upload request max total size


def _guess_content_type(filename: str) -> str:
    content_type, _ = mimetypes.guess_type(filename)
    return content_type or "application/pdf"


def _ensure_extension(filename: str, content_type: str) -> str:
    if "." in filename:
        return filename
    ext = mimetypes.guess_extension(content_type) or ".pdf"
    return f"{filename}{ext}"


def _filename_from_path(file_path: str) -> str:
    parsed = urlparse(file_path)
    path = parsed.path or file_path
    name = os.path.basename(path) or "attachment"
    return name


def _download_file_bytes(file_path: str) -> Tuple[Optional[bytes], Optional[str], Optional[str]]:
    if not file_path:
        return None, None, None

    filename = _filename_from_path(file_path)
    content_type = _guess_content_type(filename)
    filename = _ensure_extension(filename, content_type)

    try:
        if "r2.dev/" in file_path:
            key = urlparse(file_path).path.lstrip("/")
            file_obj = get_file_from_r2(key)
            if file_obj:
                return file_obj.read(), filename, content_type
        elif FILES_SERVICE_BASE_URL and file_path.startswith(FILES_SERVICE_BASE_URL):
            file_iter = get_file_from_files_service(filename)
            if file_iter:
                return b"".join(file_iter), filename, content_type
        else:
            response = httpx.get(file_path, timeout=60)
            if response.status_code < 400:
                content_type = response.headers.get("Content-Type") or content_type
                filename = _ensure_extension(filename, content_type)
                return response.content, filename, content_type
    except Exception as exc:
        print(f"QB attachment download error for {file_path}: {exc}")

    return None, None, None


async def attach_file_to_qb(
    access_token: str,
    base_url: str,
    realm_id: str,
    entity_type: str,
    entity_id: str,
    file_path: str,
    timeout: int = 30,
):
    file_bytes, filename, content_type = _download_file_bytes(file_path)
    if not file_bytes or not filename:
        return {"error": "Missing file bytes for attachment"}

    if len(file_bytes) > MAX_UPLOAD_BYTES:
        return {"error": "Attachment exceeds upload size limit"}

    metadata = {
        "AttachableRef": [
            {"EntityRef": {"type": entity_type, "value": str(entity_id)}}
        ],
        "FileName": filename,
        "ContentType": content_type,
    }

    files = {
        "file_metadata_01": (
            None,
            json.dumps(metadata),
            "application/json; charset=UTF-8",
        ),
        "file_content_01": (filename, file_bytes, content_type),
    }

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }

    url = f"{base_url}/v3/company/{realm_id}/upload"

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, files=files, headers=headers)

    if resp.status_code >= 400:
        return {"error": resp.text, "status_code": resp.status_code}

    try:
        return resp.json()
    except Exception:
        return {"raw": resp.text, "status_code": resp.status_code}
