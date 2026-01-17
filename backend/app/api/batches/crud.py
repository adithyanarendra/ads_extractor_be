import io
import zipfile
import csv
import asyncio
from re import findall
from datetime import datetime
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from calendar import month_abbr
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload
from . import models
from ...utils.r2 import get_file_from_r2
from ..invoices.models import Invoice
from .models import Batch


def _sanitize_field(value):
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)
    return value.replace(",", " ").replace("\n", " ").replace("\r", " ").strip()


async def _prepare_batch_invoice_entries(
    db: AsyncSession, batch_id: int, owner_id: int
):
    batch_result = await list_invoice_file_paths(db, batch_id, owner_id)
    if not batch_result.get("ok"):
        raise ValueError(batch_result.get("message", "Failed to fetch batch files"))

    data = batch_result["data"]
    files = data.get("files", [])
    if not files:
        raise ValueError("No files found for this batch")

    batch_name = data.get("batch_name", f"batch_{batch_id}")
    rows = []
    file_tasks = []

    from ..invoices.crud import get_invoice_by_id_and_owner

    for file in files:
        invoice = await get_invoice_by_id_and_owner(db, file["id"], owner_id)
        if not invoice:
            continue

        filename = invoice.file_path.split("/")[-1]

        if "." in filename:
            ext = filename.rsplit(".", 1)[1].lower()
        else:
            ext = "bin"

        invoice_number = invoice.invoice_number or f"INV-{invoice.id}"
        safe_filename = f"{invoice_number}.{ext}"

        file_tasks.append(
            (
                safe_filename,
                asyncio.create_task(_fetch_file_bytes(filename)),
            )
        )

        rows.append(
            [
                _sanitize_field(invoice.invoice_number),
                _sanitize_field(invoice.invoice_date),
                _sanitize_field(invoice.vendor_name),
                _sanitize_field(invoice.trn_vat_number),
                _sanitize_field(invoice.before_tax_amount),
                _sanitize_field(invoice.tax_amount),
                _sanitize_field(invoice.total),
                _sanitize_field(invoice.remarks),
            ]
        )

    if not rows:
        raise ValueError("No invoices could be processed for this batch")

    zipped_files = []
    for (safe_filename, task), content in zip(file_tasks, await asyncio.gather(*[task for _, task in file_tasks])):
        if not content:
            continue
        zipped_files.append({"filename": safe_filename, "content": content})

    return batch_name, rows, zipped_files


async def _fetch_file_bytes(filename: str) -> Optional[bytes]:
    file_obj = await asyncio.to_thread(get_file_from_r2, filename)
    if not file_obj:
        return None
    return file_obj.read()


def _ok(message: str, data=None):
    return {"ok": True, "message": message, "data": data}


def _err(message: str, error: str):
    return {"ok": False, "message": message, "error": error}


async def list_batches(db: AsyncSession, owner_id: int) -> Dict[str, Any]:
    """List all batches with invoice counts"""
    try:
        result = await db.execute(
            select(models.Batch)
            .options(
                selectinload(models.Batch.invoices),
                selectinload(models.Batch.children).selectinload(models.Batch.invoices),
            )
            .where(models.Batch.owner_id == owner_id)
            .order_by(models.Batch.created_at.desc())
        )
        rows = result.scalars().unique().all()

        data = []
        for b in rows:
            all_invoices = list(b.invoices)
            for child in b.children or []:
                all_invoices.extend(child.invoices or [])

            uploaded_invoices = [
                inv for inv in all_invoices if inv.source_sales_invoice_id is None
            ]

            sales_generated_invoices = [
                inv for inv in all_invoices if inv.source_sales_invoice_id is not None
            ]

            unpublished_invoices = [
                inv for inv in all_invoices if not getattr(inv, "is_published", False)
            ]
            data.append(
                {
                    "id": b.id,
                    "name": b.name,
                    "invoice_count": len(uploaded_invoices),
                    "sales_generated_count": len(sales_generated_invoices),
                    "invoice_count_unpublished": len(unpublished_invoices),
                    "invoice_ids": [inv.id for inv in all_invoices],
                    "parent_id": b.parent_id,
                }
            )

        return _ok("Fetched batches.", data)
    except Exception as e:
        return _err("Failed to fetch batches.", str(e))


async def create_batch(
    db: AsyncSession,
    name: str,
    owner_id: int,
    invoice_ids: Optional[List[int]] = None,
    batch_year: Optional[int] = None,
    parent_id: Optional[int] = None,
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
        if not batch_year:
            years = findall(r"\b(20\d{2})\b", name)
            batch_year = int(years[0]) if years else None
        new_batch = models.Batch(
            name=name,
            locked=False,
            owner_id=owner_id,
            created_at=now,
            updated_at=now,
            batch_year=batch_year,
            parent_id=parent_id,
        )

        db.add(new_batch)
        await db.flush()

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
            {
                "id": new_batch.id,
                "name": new_batch.name,
                "locked": new_batch.locked,
                "parent_id": new_batch.parent_id,
            },
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
                .options(
                    selectinload(models.Batch.invoices),
                    selectinload(models.Batch.children).selectinload(
                        models.Batch.invoices
                    ),
                )
                .where(models.Batch.id == batch_id, models.Batch.owner_id == owner_id)
            )
        ).scalar_one_or_none()

        if not batch:
            return _err("Batch not found.", "not_found")

        all_invoices = list(batch.invoices or [])
        for child in batch.children or []:
            all_invoices.extend(child.invoices or [])

        files = []
        for inv in all_invoices:
            if inv.file_path:
                files.append(
                    {
                        "id": inv.id,
                        "invoice_number": getattr(
                            inv, "invoice_number", f"INV-{inv.id}"
                        ),
                        "file_path": inv.file_path,
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
        print("ERR list_invoice_file_paths:", e)
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
                select(models.Batch)
                .options(selectinload(models.Batch.parent))
                .where(models.Batch.id == batch_id, models.Batch.owner_id == owner_id)
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

        if batch.parent_id:
            parent_id = batch.parent_id

            # Fetch parent batch
            parent_batch = (
                await db.execute(
                    select(models.Batch)
                    .where(models.Batch.id == parent_id)
                    .options(selectinload(models.Batch.invoices))
                )
            ).scalar_one_or_none()

            if parent_batch:
                existing_parent_invoice_ids = {inv.id for inv in parent_batch.invoices}
                new_parent_invoice_ids = set(verified_ids) - existing_parent_invoice_ids

                if new_parent_invoice_ids:
                    parent_batch.invoices.extend(
                        [
                            inv
                            for inv in verified_invoices
                            if inv.id in new_parent_invoice_ids
                        ]
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
    from ..invoices.crud import get_invoice_by_id_and_owner

    """
    Returns a BytesIO object containing a ZIP file with:
    - All invoice PDFs in the batch
    - A CSV summary file (sanitized)
    Also returns the batch name.
    """
    batch_name, rows, files = await _prepare_batch_invoice_entries(
        db, batch_id, owner_id
    )

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

    for row in rows:
        csv_writer.writerow(row)

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for file in files:
            zip_file.writestr(file["filename"], file["content"])
        csv_filename = f"{batch_name}_summary.csv"
        zip_file.writestr(csv_filename, csv_buffer.getvalue())

    zip_buffer.seek(0)
    return zip_buffer, batch_name


async def generate_batch_csv(
    db: AsyncSession, batch_id: int, owner_id: int
) -> tuple[io.StringIO, str]:
    batch_name, rows, _ = await _prepare_batch_invoice_entries(
        db, batch_id, owner_id
    )
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
    for row in rows:
        csv_writer.writerow(row)
    csv_buffer.seek(0)
    return csv_buffer, batch_name


async def generate_batch_images_zip(
    db: AsyncSession, batch_id: int, owner_id: int
) -> tuple[io.BytesIO, str]:
    batch_name, _, files = await _prepare_batch_invoice_entries(
        db, batch_id, owner_id
    )
    if not files:
        raise ValueError("No invoice files found for this batch")

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for file in files:
            zip_file.writestr(file["filename"], file["content"])
    zip_buffer.seek(0)
    return zip_buffer, batch_name


async def get_invoice_ids_for_batch(
    db: AsyncSession, batch_id: int, owner_id: int
) -> Dict[str, Any]:
    """Return all invoice IDs for a given batch"""
    try:
        batch = (
            await db.execute(
                select(models.Batch)
                .options(
                    selectinload(models.Batch.invoices),
                    selectinload(models.Batch.children).selectinload(
                        models.Batch.invoices
                    ),
                )
                .where(models.Batch.id == batch_id, models.Batch.owner_id == owner_id)
            )
        ).scalar_one_or_none()

        if not batch:
            return _err("Batch not found.", "not_found")

        all_ids = [inv.id for inv in (batch.invoices or [])]

        for child in batch.children or []:
            all_ids.extend([inv.id for inv in (child.invoices or [])])

        all_ids = list(set(all_ids))

        return _ok(
            "Fetched invoice IDs.",
            {"batch_id": batch.id, "invoice_ids": all_ids},
        )

    except Exception as e:
        return _err("Failed to fetch invoice IDs.", str(e))


async def get_batch_with_invoices(
    db: AsyncSession, batch_id: int, owner_id: int
) -> Optional[Batch]:
    """Fetch a batch with invoices (including children) for the owner."""
    result = await db.execute(
        select(models.Batch)
        .options(
            selectinload(models.Batch.invoices),
            selectinload(models.Batch.children).selectinload(models.Batch.invoices),
        )
        .where(models.Batch.id == batch_id, models.Batch.owner_id == owner_id)
    )
    return result.scalar_one_or_none()


async def get_invoices_with_coas_for_batch(
    db: AsyncSession, batch_id: int, owner_id: int
) -> list[dict]:
    """Return all invoices in a batch (including children) with their COA selections."""
    batch = await get_batch_with_invoices(db, batch_id, owner_id)
    if not batch:
        return []

    invoices = list(batch.invoices or [])
    for child in batch.children or []:
        invoices.extend(child.invoices or [])

    # Only surface invoices that are not yet published (already-pushed ones stay visible in the full batch view via /batches/{id})
    invoices = [inv for inv in invoices if not getattr(inv, "is_published", False)]

    data = []
    for inv in invoices:
        data.append(
            {
                "id": inv.id,
                "invoice_number": inv.invoice_number,
                "vendor_name": inv.vendor_name,
                "bill_date": getattr(inv, "invoice_date", None),
                "description": inv.description or inv.vendor_name,
                "amount": float(inv.total or inv.before_tax_amount or 0),
                "chart_of_account_id": inv.chart_of_account_id,
                "chart_of_account_name": inv.chart_of_account_name,
                "type": getattr(inv, "type", None),
            }
        )

    return data


MONTH_MAP = {m.lower(): i for i, m in enumerate(month_abbr) if m}


def parse_batch_range(batch_name: str):
    """
    Parse batch name like 'Feb - Apr 2025' → (2, 4, 2025)
    """
    try:
        parts = batch_name.split()
        if len(parts) < 3:
            return None

        months = [p for p in parts if p.strip("-").isalpha()]
        year = int(parts[-1])
        if len(months) != 2:
            return None
        start_month = MONTH_MAP.get(months[0][:3].lower())
        end_month = MONTH_MAP.get(months[1][:3].lower())
        if not start_month or not end_month:
            return None
        if end_month < start_month:
            start_year = year - 1
            end_year = year
        else:
            start_year = end_year = year

        return (start_month, end_month, start_year, end_year)
    except Exception:
        return None

def parse_single_month_batch(name: str):
    """
    Parse 'Feb 2025' → (2, 2025)
    """
    try:
        parts = name.strip().split()
        if len(parts) != 2:
            return None
        month, year = parts
        month_num = MONTH_MAP.get(month[:3].lower())
        if not month_num:
            return None
        return (month_num, int(year))
    except Exception:
        return None


async def find_matching_batch_for_invoice(
    db: AsyncSession, owner_id: int, invoice_date: datetime | str
):
    exact_match = None
    range_match = None

    try:
        if not invoice_date:
            return None

        if isinstance(invoice_date, datetime):
            date_obj = invoice_date
        elif isinstance(invoice_date, str):
            date_obj = datetime.strptime(invoice_date, "%d-%m-%Y")
        else:
            return None
        inv_month, inv_year = date_obj.month, date_obj.year

        result = await db.execute(
            select(models.Batch).where(models.Batch.owner_id == owner_id)
        )
        batches = result.scalars().all()

        for b in batches:
            single = parse_single_month_batch(b.name)
            if single:
                m, y = single
                if y == inv_year and m == inv_month:
                    exact_match = b.id
                    break

            parsed = parse_batch_range(b.name)
            if parsed:
                start_m, end_m, start_y, end_y = parsed
                if start_y == end_y == inv_year and start_m <= inv_month <= end_m:
                    range_match = b.id
        return exact_match or range_match
    except Exception as e:
        print("⚠️ find_matching_batch_for_invoice error:", e)
        return None


# ------------------------------------------------------------------
# AUTO-GENERATE FUTURE BATCHES (3-month cycles)
# ------------------------------------------------------------------

def _format_batch_name(start_month: int, start_year: int, end_month: int, end_year: int) -> str:
    """Format batch name like 'Feb - Apr 2025' or cross-year 'Nov 2025 - Jan 2026'."""
    start_name = month_abbr[start_month]
    end_name = month_abbr[end_month]
    if start_year == end_year:
        return f"{start_name} - {end_name} {end_year}"
    return f"{start_name} {start_year} - {end_name} {end_year}"


def _next_quarter_ranges(current_end_month: int, current_end_year: int) -> List[Dict[str, int]]:
    """
    Given the end month/year of the latest batch, return the next four 3-month ranges.
    Months are 1-based (Jan=1).
    """
    ranges = []
    start_month = current_end_month % 12 + 1
    start_year = current_end_year if start_month > current_end_month else current_end_year + 1

    for _ in range(4):
        end_month = (start_month + 2 - 1) % 12 + 1  # 3-month window
        end_year = start_year if end_month >= start_month else start_year + 1
        ranges.append(
            {
                "start_month": start_month,
                "end_month": end_month,
                "start_year": start_year,
                "end_year": end_year,
            }
        )
        # move to next quarter
        start_month = end_month % 12 + 1
        start_year = end_year if start_month > end_month else end_year + 1

    return ranges


async def _create_child_batches_for_range(
    db: AsyncSession,
    owner_id: int,
    parent_id: int,
    start_month: int,
    end_month: int,
    start_year: int,
    end_year: int,
):
    """Create monthly child batches for a 3-month parent range."""
    month = start_month
    year = start_year

    while True:
        child_name = f"{month_abbr[month]} {year}"
        try:
            await create_batch(
                db,
                name=child_name,
                owner_id=owner_id,
                invoice_ids=None,
                batch_year=year,
                parent_id=parent_id,
            )
        except Exception:
            # ignore duplicates
            pass

        if year == end_year and month == end_month:
            break

        month += 1
        if month > 12:
            month = 1
            year += 1


async def ensure_future_batches(db: AsyncSession, owner_id: int):
    """
    If the latest parent batch has ended (or ends this month), create the next 4 quarterly batches
    and their monthly children. Skips duplicates.
    """
    result = await db.execute(
        select(models.Batch)
        .where(models.Batch.owner_id == owner_id, models.Batch.parent_id.is_(None))
        .order_by(models.Batch.created_at.desc())
        .limit(1)
    )
    latest = result.scalar_one_or_none()
    if not latest:
        return

    parsed = parse_batch_range(latest.name)
    if not parsed:
        return

    start_month, end_month, start_year, end_year = parsed

    now = datetime.now(timezone.utc)
    # Trigger when we are within the last month of the latest batch (or later)
    current_index = now.year * 12 + now.month
    end_index = end_year * 12 + end_month
    if current_index < end_index - 1:
        return

    next_ranges = _next_quarter_ranges(end_month, end_year)

    for r in next_ranges:
        parent_name = _format_batch_name(
            r["start_month"], r["start_year"], r["end_month"], r["end_year"]
        )
        parent_id = None
        res = await create_batch(
            db,
            name=parent_name,
            owner_id=owner_id,
            invoice_ids=None,
            batch_year=r["end_year"],
            parent_id=None,
        )
        if res.get("ok"):
            parent_id = res["data"]["id"]
        else:
            # try to fetch existing if duplicate
            existing = (
                await db.execute(
                    select(models.Batch).where(
                        models.Batch.owner_id == owner_id, models.Batch.name == parent_name
                    )
                )
            ).scalar_one_or_none()
            parent_id = existing.id if existing else None

        if parent_id:
            await _create_child_batches_for_range(
                db,
                owner_id,
                parent_id,
                r["start_month"],
                r["end_month"],
                r["start_year"],
                r["end_year"],
            )

async def remove_invoice_from_batch(
    db: AsyncSession, batch_id: int, invoice_id: int, owner_id: int
):
    try:
        batch = (
            await db.execute(
                select(models.Batch)
                .options(selectinload(models.Batch.children))
                .where(models.Batch.id == batch_id, models.Batch.owner_id == owner_id)
            )
        ).scalar_one_or_none()

        if not batch:
            return _err("Batch not found.", "not_found")

        if batch.locked:
            return _err("Cannot modify a locked batch.", "locked")

        invoice = (
            await db.execute(
                select(Invoice).where(
                    Invoice.id == invoice_id,
                    Invoice.owner_id == owner_id,
                )
            )
        ).scalar_one_or_none()

        if not invoice:
            return _err("Invoice not found.", "not_found")

        if invoice.batch_id == batch_id:
            await db.execute(
                update(Invoice).where(Invoice.id == invoice_id).values(batch_id=None)
            )

        else:
            found_child = None
            for child in batch.children:
                if invoice.batch_id == child.id:
                    found_child = child.id
                    break

            if not found_child:
                return _err(
                    "Invoice does not belong to this batch or its children.",
                    "invalid_batch_invoice",
                )

            await db.execute(
                update(Invoice).where(Invoice.id == invoice_id).values(batch_id=None)
            )

        batch.updated_at = datetime.now(timezone.utc)
        await db.commit()

        return _ok(
            "Invoice removed from batch.",
            {
                "batch_id": batch_id,
                "invoice_id": invoice_id,
            },
        )

    except Exception as e:
        await db.rollback()
        return _err("Failed to remove invoice from batch.", str(e))


async def clear_all_invoices_from_batch(db: AsyncSession, batch_id: int, owner_id: int):
    try:
        batch = (
            await db.execute(
                select(models.Batch)
                .options(selectinload(models.Batch.children))
                .where(models.Batch.id == batch_id, models.Batch.owner_id == owner_id)
            )
        ).scalar_one_or_none()

        if not batch:
            return _err("Batch not found.", "not_found")

        if batch.locked:
            return _err("Cannot reset a locked batch.", "locked")

        child_ids = [child.id for child in batch.children]

        if child_ids:
            await db.execute(
                update(Invoice)
                .where(Invoice.batch_id.in_(child_ids), Invoice.owner_id == owner_id)
                .values(batch_id=None)
            )

        await db.execute(
            update(Invoice)
            .where(Invoice.batch_id == batch_id, Invoice.owner_id == owner_id)
            .values(batch_id=None)
        )

        batch.updated_at = datetime.now(timezone.utc)
        await db.commit()

        return _ok(
            "Batch reset complete. All invoices removed.",
            {"batch_id": batch_id},
        )

    except Exception as e:
        await db.rollback()
        return _err("Failed to reset batch.", str(e))


async def get_invoices_for_qb_batch_status(
    db: AsyncSession, batch_id: int, owner_id: int
):
    """
    Fetches key invoice details (including COA) for the QuickBooks pre-push dialog.
    It specifically filters out invoices that are already published.
    """
    batch_with_invoices = await db.execute(
        select(models.Batch)
        .options(
            selectinload(models.Batch.invoices),
            selectinload(models.Batch.children).selectinload(models.Batch.invoices),
        )
        .where(models.Batch.id == batch_id, models.Batch.owner_id == owner_id)
    )
    batch = batch_with_invoices.scalar_one_or_none()

    if not batch:
        return []

    all_invoices = []

    for inv in batch.invoices:
        if not inv.is_published:
            all_invoices.append(inv)

    for child in batch.children or []:
        for inv in child.invoices:
            if not inv.is_published:
                all_invoices.append(inv)

    data = []
    for inv in all_invoices:
        data.append(
            {
                "id": inv.id,
                "invoice_number": inv.invoice_number,
                "vendor_name": inv.vendor_name,
                "chart_of_account_id": inv.chart_of_account_id,
                "chart_of_account_name": inv.chart_of_account_name,
            }
        )
    return data
