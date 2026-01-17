from datetime import datetime
from typing import Dict, Optional

from fastapi import APIRouter, Depends, status, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ..invoices.routes import get_current_user
from . import crud as reports_crud
from .pdf_renderer import render_pnl_report_pdf, render_vat_report_pdf

from ...utils.r2 import upload_to_r2_bytes, get_file_from_r2


router = APIRouter(prefix="/reports", tags=["reports"])


class ReportPDFStoreRequest(BaseModel):
    report_data: Dict[str, Optional[object]]
    report_name: Optional[str] = None


@router.get("/generate/vat_summary")
async def vat_summary(
    db: AsyncSession = Depends(get_db), current_user: int = Depends(get_current_user)
):
    result = await reports_crud.get_vat_summary(db, current_user.effective_user_id)

    if not result["ok"]:
        return {**result, "http_status": status.HTTP_400_BAD_REQUEST}

    return result


@router.get("/generate/pnl")
async def generate_pnl(
    start_date: str,
    end_date: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    result = await reports_crud.generate_pnl_report(
        db,
        current_user.effective_user_id,
        start_date,
        end_date,
    )
    return result

@router.get("/generate/monthwise_pnl")
async def generate_monthwise_pnl(
    year: int,
    month: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    result = await reports_crud.generate_monthwise_pnl_report(
        db, current_user.effective_user_id, year, month
    )
    if not result["ok"]:
        return {**result, "http_status": status.HTTP_400_BAD_REQUEST}
    return result


@router.get("/generate/vat_by_batch/{batch_id}")
async def vat_summary_by_batch(
    batch_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    result = await reports_crud.get_vat_summary_by_batch(
        db, current_user.effective_user_id, batch_id
    )
    return result


@router.get("/all")
async def list_reports(
    db: AsyncSession = Depends(get_db), current_user=Depends(get_current_user)
):
    reports = await reports_crud.get_all_reports(db, current_user.effective_user_id)

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
        filename = f"{current_user.effective_user_id}/{type}/{file.filename}"

        file_url = upload_to_r2_bytes(content, filename)

        result = await reports_crud.create_report(
            db,
            user_id=current_user.effective_user_id,
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


def _render_report_pdf(report_type: str, data: Dict[str, Optional[object]]) -> bytes:
    if report_type == "vat_pdf":
        return render_vat_report_pdf(data)
    if report_type == "pnl_pdf":
        return render_pnl_report_pdf(data)

    raise HTTPException(status_code=400, detail="Unsupported PDF type")


@router.post("/store/{type}")
async def store_generated_pdf(
    type: str,
    payload: ReportPDFStoreRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    try:
        report_data = dict(payload.report_data or {})
        report_data.setdefault("generated_at", datetime.utcnow().strftime("%Y-%m-%d %H:%M"))
        pdf_bytes = _render_report_pdf(type, report_data)
        timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        name = payload.report_name or f"{timestamp}_{type}.pdf"
        filename = f"{current_user.effective_user_id}/{type}/{name}"
        file_url = upload_to_r2_bytes(pdf_bytes, filename)

        result = await reports_crud.create_report(
            db,
            user_id=current_user.effective_user_id,
            report_name=name,
            type=type,
            file_path=file_url,
        )
        return result

    except HTTPException:
        raise
    except Exception as e:
        return {
            "ok": False,
            "message": "Failed to generate report PDF",
            "error": str(e),
            "data": None,
        }


@router.get("/view/{report_id}")
async def view_report(
    report_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    report = await reports_crud.get_report(
        db, report_id, current_user.effective_user_id
    )

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
