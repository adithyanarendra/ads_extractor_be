import requests
from fastapi import UploadFile
from io import BytesIO
from ..core.config import FILES_SERVICE_API_KEY, FILES_SERVICE_BASE_URL

HEADERS = {"x-api-key": FILES_SERVICE_API_KEY}


def upload_to_files_service(file_obj: UploadFile | bytes, filename: str) -> str:
    """
    Upload a file to the local files service.
    Returns the public URL of the uploaded file.
    """
    files = {}
    if isinstance(file_obj, UploadFile):
        files = {
            "file": (
                filename,
                file_obj.file,
                file_obj.content_type or "application/octet-stream",
            )
        }
    else:  # bytes
        files = {"file": (filename, BytesIO(file_obj), "application/octet-stream")}

    response = requests.post(
        f"{FILES_SERVICE_BASE_URL}/files/upload",
        headers=HEADERS,
        files=files,
        timeout=60,
    )
    response.raise_for_status()
    return response.json()["url"]


def upload_to_files_service_bytes(content: bytes, filename: str) -> str:
    """
    Upload raw bytes directly to the files service.
    Returns the public URL.
    """
    from io import BytesIO

    files = {"file": (filename, BytesIO(content), "application/octet-stream")}

    response = requests.post(
        f"{FILES_SERVICE_BASE_URL}/files/upload",
        headers=HEADERS,
        files=files,
        timeout=60,
    )
    response.raise_for_status()
    return response.json()["url"]


def get_file_from_files_service(filename: str):
    """
    Returns a streaming response (bytes-like) from files service.
    """
    response = requests.get(
        f"{FILES_SERVICE_BASE_URL}/files/download/{filename}",
        headers=HEADERS,
        stream=True,
        timeout=60,
    )
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.iter_content(chunk_size=1024 * 8)  # generator for streaming


def delete_file_from_files_service(filename: str):
    """
    Delete a file from the files service.
    """
    response = requests.delete(
        f"{FILES_SERVICE_BASE_URL}/files/{filename}", headers=HEADERS, timeout=30
    )
    response.raise_for_status()
    return response.json().get("ok", False)
