from fastapi import APIRouter, Depends, status, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse

from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ..invoices.routes import get_current_user
from .crud import (
    get_vat_summary,
    get_all_reports,
    get_report,
    create_report,
    get_vat_summary_by_batch,
)
from ...utils.r2 import upload_to_r2_bytes, get_file_from_r2

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/generate/vat_summary")
async def vat_summary(
    db: AsyncSession = Depends(get_db), current_user: int = Depends(get_current_user)
):
    result = await get_vat_summary(db, current_user.id)

    if not result["ok"]:
        return {**result, "http_status": status.HTTP_400_BAD_REQUEST}

    return result


@router.get("/generate/vat_by_batch/{batch_id}")
async def vat_summary_by_batch(
    batch_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    result = await get_vat_summary_by_batch(db, current_user.id, batch_id)
    return result


@router.get("/all")
async def list_reports(
    db: AsyncSession = Depends(get_db), current_user=Depends(get_current_user)
):
    reports = await get_all_reports(db, current_user.id)

    return {
        "ok": True,
        "message": "Reports fetched",
        "error": None,
        "data": [
            {
                "id": r.id,
                "name": r.report_name,
                "type": r.type,
                "uploaded_at": r.uploaded_at,
            }
            for r in reports
        ],
    }


@router.post("/upload/{type}")
async def upload_report(
    type: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    try:
        content = await file.read()
        filename = f"{current_user.id}/{type}/{file.filename}"

        file_url = upload_to_r2_bytes(content, filename)

        result = await create_report(
            db,
            user_id=current_user.id,
            report_name=file.filename,
            type=type,
            file_path=file_url,
        )
        return result

    except Exception as e:
        return {
            "ok": False,
            "message": "Upload failed",
            "error": str(e),
            "data": None,
        }


@router.get("/view/{report_id}")
async def view_report(
    report_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    report = await get_report(db, report_id, current_user.id)

    if not report:
        return {
            "ok": False,
            "message": "Report not found",
            "error": "NOT_FOUND",
            "data": None,
        }

    file_key = report.file_path.split(".r2.dev/")[-1]

    file_obj = get_file_from_r2(file_key)

    if not file_obj:
        raise HTTPException(status_code=404, detail="File not found in R2")

    return StreamingResponse(file_obj, media_type="application/octet-stream")
