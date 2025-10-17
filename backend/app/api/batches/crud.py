import io
import zipfile
import csv
from ...utils.r2 import get_file_from_r2
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload
from . import models
from app.api.invoices.models import Invoice
from ..invoices.crud import get_invoice_by_id_and_owner


def _ok(message: str, data=None):
    return {"ok": True, "message": message, "data": data}


def _err(message: str, error: str):
    return {"ok": False, "message": message, "error": error}


async def list_batches(db: AsyncSession, owner_id: int) -> Dict[str, Any]:
    """List all batches with invoice counts"""
    try:
        result = await db.execute(
            select(models.Batch)
            .options(selectinload(models.Batch.invoices))
            .where(models.Batch.owner_id == owner_id)
            .order_by(models.Batch.created_at.desc())
        )
        rows = result.scalars().all()
        data = [
            {
                "id": b.id,
                "name": b.name,
                "locked": b.locked,
                "created_at": b.created_at.isoformat() if b.created_at else None,
                "invoice_count": len(b.invoices) if b.invoices else 0,
            }
            for b in rows
        ]
        return _ok("Fetched batches.", data)
    except Exception as e:
        return _err("Failed to fetch batches.", str(e))


async def create_batch(
    db: AsyncSession, name: str, owner_id: int, invoice_ids: Optional[List[int]] = None
) -> Dict[str, Any]:
    """Create a new batch and assign invoices"""
    try:
        existing = (
            await db.execute(
                select(models.Batch).where(
                    models.Batch.name == name, models.Batch.owner_id == owner_id
                )
            )
        ).scalar_one_or_none()
        if existing:
            return _err("Batch name already exists.", "duplicate")

        # ✅ Add timestamps
        now = datetime.now(timezone.utc)
        new_batch = models.Batch(
            name=name, locked=False, owner_id=owner_id, created_at=now, updated_at=now
        )

        db.add(new_batch)
        await db.flush()  # ensures batch.id is available

        # Attach invoices (if provided)
        if invoice_ids:
            await db.execute(
                update(Invoice)
                .where(Invoice.id.in_(invoice_ids))
                .values(batch_id=new_batch.id)
            )

        await db.commit()
        await db.refresh(new_batch)
        return _ok(
            "Batch created.",
            {"id": new_batch.id, "name": new_batch.name, "locked": new_batch.locked},
        )
    except Exception as e:
        await db.rollback()
        return _err("Failed to create batch.", str(e))


async def toggle_lock(db: AsyncSession, batch_id: int, owner_id: int) -> Dict[str, Any]:
    """Lock or unlock a batch"""
    try:
        batch = (
            await db.execute(
                select(models.Batch).where(
                    models.Batch.id == batch_id, models.Batch.owner_id == owner_id
                )
            )
        ).scalar_one_or_none()
        if not batch:
            return _err("Batch not found.", "not_found")

        batch.locked = not bool(batch.locked)
        batch.updated_at = datetime.now(timezone.utc)  # ✅ update timestamp
        await db.commit()
        await db.refresh(batch)
        return _ok("Lock toggled.", {"id": batch.id, "locked": batch.locked})
    except Exception as e:
        await db.rollback()
        return _err("Failed to toggle lock.", str(e))


async def list_invoice_file_paths(
    db: AsyncSession, batch_id: int, owner_id: int
) -> Dict[str, Any]:
    """Get file URLs for all invoices inside a batch"""
    try:
        batch = (
            await db.execute(
                select(models.Batch)
                .options(selectinload(models.Batch.invoices))
                .where(models.Batch.id == batch_id, models.Batch.owner_id == owner_id)
            )
        ).scalar_one_or_none()
        if not batch:
            return _err("Batch not found.", "not_found")

        files = []
        for inv in batch.invoices or []:
            file_path = getattr(inv, "file_path", None)
            if file_path:
                files.append(
                    {
                        "id": inv.id,
                        "invoice_number": getattr(
                            inv, "invoice_number", f"INV-{inv.id}"
                        ),
                        "file_path": file_path,
                    }
                )

        if not files:
            return _err("No files found for invoices.", "no_files")

        return _ok(
            "File paths prepared.",
            {
                "batch_id": batch.id,
                "batch_name": batch.name,
                "files": files,
                "count": len(files),
            },
        )
    except Exception as e:
        return _err("Failed to fetch invoice file paths.", str(e))


async def delete_batch_if_unlocked(
    db: AsyncSession, batch_id: int, owner_id: int
) -> Dict[str, Any]:
    """Delete a batch only if it’s not locked"""
    try:
        batch = (
            await db.execute(
                select(models.Batch).where(
                    models.Batch.id == batch_id, models.Batch.owner_id == owner_id
                )
            )
        ).scalar_one_or_none()
        if not batch:
            return _err("Batch not found.", "not_found")
        if batch.locked:
            return _err("Cannot delete a locked batch.", "locked")

        # Unassign invoices first
        await db.execute(
            update(Invoice).where(Invoice.batch_id == batch_id).values(batch_id=None)
        )

        await db.delete(batch)
        await db.commit()
        return _ok("Batch deleted.", {"id": batch_id, "name": batch.name})
    except Exception as e:
        await db.rollback()
        return _err("Failed to delete batch.", str(e))


async def add_invoices_to_batch(
    db: AsyncSession, batch_id: int, invoice_ids: List[int], owner_id: int
) -> dict:
    """Add veridied only invoices to an existing batch owned by the user"""
    try:
        if not invoice_ids:
            return _err("No invoices provided to add.", "empty_array")

        # Fetch the batch and ensure it belongs to the owner
        batch = (
            await db.execute(
                select(models.Batch).where(
                    models.Batch.id == batch_id, models.Batch.owner_id == owner_id
                )
            )
        ).scalar_one_or_none()

        if not batch:
            return _err("Batch not found or you do not have permission.", "not_found")

        if batch.locked:
            return _err("Cannot modify a locked batch.", "locked")

        result = await db.execute(
            select(Invoice).where(
                Invoice.id.in_(invoice_ids),
                Invoice.owner_id == owner_id,
                Invoice.reviewed == True,
            )
        )
        verified_invoices = result.scalars().all()
        verified_ids = [inv.id for inv in verified_invoices]

        if not verified_invoices:
            return _err(
                "None of the provided invoices are verified. Only verified invoices can be added.",
                "unverified_invoices",
            )

        await db.execute(
            update(Invoice)
            .where(Invoice.id.in_(verified_ids))
            .values(batch_id=batch_id)
        )

        batch.updated_at = datetime.now(timezone.utc)
        await db.commit()
        return _ok(
            "Invoices added to batch.",
            {"batch_id": batch.id, "added_invoice_ids": invoice_ids},
        )
    except Exception as e:
        await db.rollback()
        return _err("Failed to add invoices to batch.", str(e))


async def generate_batch_zip_with_csv(
    db: AsyncSession, batch_id: int, owner_id: int
) -> tuple[io.BytesIO, str]:
    """
    Returns a BytesIO object containing a ZIP file with:
    - All invoice PDFs in the batch
    - A CSV summary file (sanitized)
    Also returns the batch name.
    """
    batch_result = await list_invoice_file_paths(db, batch_id, owner_id)
    if not batch_result.get("ok"):
        raise ValueError(batch_result.get("message", "Failed to fetch batch files"))

    data = batch_result["data"]
    files = data.get("files", [])
    if not files:
        raise ValueError("No files found for this batch")

    zip_buffer = io.BytesIO()
    csv_buffer = io.StringIO()
    csv_writer = csv.writer(csv_buffer, quoting=csv.QUOTE_ALL)
    csv_writer.writerow(
        [
            "Invoice Number",
            "Invoice Date",
            "Vendor Name",
            "TRN/VAT Number",
            "Before Tax Amount",
            "Tax Amount",
            "Total",
            "Remarks",
        ]
    )

    def sanitize_field(value):
        if value is None:
            return ""
        if not isinstance(value, str):
            value = str(value)
        return value.replace(",", " ").replace("\n", " ").replace("\r", " ").strip()

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for file in files:
            # Fetch full invoice using id + owner
            invoice = await get_invoice_by_id_and_owner(db, file["id"], owner_id)
            if not invoice:
                continue

            # Add PDF to ZIP
            filename = invoice.file_path.split("/")[-1]
            invoice_obj = get_file_from_r2(filename)
            if invoice_obj:
                file_bytes = invoice_obj.read()
                zip_file.writestr(
                    f"{invoice.invoice_number or invoice.id}.pdf", file_bytes
                )

            # Add CSV row
            csv_writer.writerow(
                [
                    sanitize_field(invoice.invoice_number),
                    sanitize_field(invoice.invoice_date),
                    sanitize_field(invoice.vendor_name),
                    sanitize_field(invoice.trn_vat_number),
                    sanitize_field(invoice.before_tax_amount),
                    sanitize_field(invoice.tax_amount),
                    sanitize_field(invoice.total),
                    sanitize_field(invoice.remarks),
                ]
            )

        # Write CSV to ZIP
        csv_filename = f"{data.get('batch_name', f'batch_{batch_id}')}_summary.csv"
        zip_file.writestr(csv_filename, csv_buffer.getvalue())

    zip_buffer.seek(0)
    return zip_buffer, data.get("batch_name", f"batch_{batch_id}")
