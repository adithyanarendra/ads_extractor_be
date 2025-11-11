import os
from uuid import uuid4
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from .models import Statement, StatementItem
from ...utils.r2 import upload_to_r2_bytes, get_file_from_r2
from .service import parse_statement
from ...core.database import SessionLocal

ALLOWED_TYPES = ("bank", "credit_card")


async def create_statement(
    db: AsyncSession,
    user,
    statement_type: str,
    file_bytes: bytes,
    filename: str,
    skip_parsing: bool = False,
):
    try:
        if statement_type not in ALLOWED_TYPES:
            return {
                "ok": False,
                "message": "Invalid statement type",
                "error": "Type not allowed",
                "data": None,
            }

        file_ext = os.path.splitext(filename)[1]
        file_key = f"statements/{user.id}/{uuid4()}{file_ext}"
        file_url = upload_to_r2_bytes(file_bytes, file_key)

        stmt = Statement(
            owner_id=user.id,
            statement_type=statement_type,
            file_name=filename,
            file_key=file_key,
            file_url=file_url,
        )

        db.add(stmt)
        await db.flush()
        await db.refresh(stmt)

        if skip_parsing:
            return {
                "ok": True,
                "message": "Statement stored successfully",
                "error": None,
                "data": stmt,
            }

        await db.commit()
        return {
            "ok": True,
            "message": "Statement uploaded successfully",
            "error": None,
            "data": stmt,
        }

    except Exception as e:
        return {
            "ok": False,
            "message": "Failed to process statement",
            "error": str(e),
            "data": None,
        }


async def process_statement_background(
    statement_id: int, file_bytes: bytes, file_ext: str
):
    """
    Fully async background task using asyncio.create_task().
    Runs in its own DB session and does NOT block API response.
    """
    async with SessionLocal() as db:
        try:
            stmt = await db.get(Statement, statement_id)
            if not stmt:
                print("Statement not found for background parsing:", statement_id)
                return

            parsed = await parse_statement(file_bytes, f".{file_ext}")
            transactions = parsed.get("transactions", [])

            for tx in transactions:
                db.add(
                    StatementItem(
                        statement_id=statement_id,
                        transaction_date=tx.get("date"),
                        description=tx.get("description"),
                        transaction_type=tx.get("transaction_type"),
                        amount=tx.get("amount"),
                        balance=tx.get("balance"),
                    )
                )

            await db.commit()
            print(f"✅ Background parsing completed for statement {statement_id}")

        except Exception as e:
            print("❌ Background parsing failed:", e)


async def list_statements(db: AsyncSession, user):
    try:
        result = await db.execute(
            select(Statement).where(Statement.owner_id == user.id)
        )
        statements = result.scalars().all()

        cleaned = [
            {
                "id": s.id,
                "owner_id": s.owner_id,
                "statement_type": s.statement_type,
                "file_name": s.file_name,
                "file_url": s.file_url,
                "uploaded_at": s.uploaded_at,
            }
            for s in statements
        ]

        return {
            "ok": True,
            "message": "Statements retrieved",
            "error": None,
            "data": cleaned,
        }
    except Exception as e:
        return {
            "ok": False,
            "message": "Failed to list statements",
            "error": str(e),
            "data": None,
        }


async def list_statement_items(db: AsyncSession, user):
    try:
        result = await db.execute(
            select(StatementItem)
            .join(Statement, StatementItem.statement_id == Statement.id)
            .where(Statement.owner_id == user.id)
        )
        rows = result.scalars().all()

        return {
            "ok": True,
            "message": "Statement items retrieved",
            "error": None,
            "data": rows,
        }

    except Exception as e:
        return {
            "ok": False,
            "message": "Failed to list items",
            "error": str(e),
            "data": None,
        }


async def get_statement(db: AsyncSession, statement_id: int, user):
    try:
        stmt = await db.get(Statement, statement_id)

        if not stmt or stmt.owner_id != user.id:
            return {
                "ok": False,
                "message": "Statement not found or access denied",
                "error": "Unauthorized or missing",
                "data": None,
            }

        return {
            "ok": True,
            "message": "Statement retrieved",
            "error": None,
            "data": stmt,
        }

    except Exception as e:
        return {
            "ok": False,
            "message": "Failed to get statement",
            "error": str(e),
            "data": None,
        }


async def download_file(stmt: Statement):
    try:
        if not stmt.file_key:
            return {
                "ok": False,
                "message": "No file found for this statement",
                "error": "Missing R2 file_key",
                "data": None,
            }

        file_obj = get_file_from_r2(stmt.file_key)

        if not file_obj:
            return {
                "ok": False,
                "message": "File missing in R2",
                "error": "Not found in R2",
                "data": None,
            }

        return {
            "ok": True,
            "message": "File retrieved",
            "error": None,
            "data": file_obj,
        }

    except Exception as e:
        return {
            "ok": False,
            "message": "Failed to fetch file",
            "error": str(e),
            "data": None,
        }


async def delete_statement(db: AsyncSession, statement_id: int, user):
    try:
        stmt = await db.get(Statement, statement_id)

        if not stmt or stmt.owner_id != user.id:
            return {
                "ok": False,
                "message": "Statement not found or access denied",
                "error": "Unauthorized or missing",
                "data": None,
            }

        await db.delete(stmt)
        await db.commit()

        return {
            "ok": True,
            "message": "Statement deleted successfully",
            "error": None,
            "data": {"deleted_id": statement_id},
        }

    except Exception as e:
        return {
            "ok": False,
            "message": "Failed to delete statement",
            "error": str(e),
            "data": None,
        }


async def delete_statement_item(db: AsyncSession, item_id: int, user):
    try:
        item = await db.get(StatementItem, item_id)

        if not item:
            return {
                "ok": False,
                "message": "Statement item not found",
                "error": "Missing",
                "data": None,
            }

        # Ensure item belongs to the user
        stmt = await db.get(Statement, item.statement_id)
        if not stmt or stmt.owner_id != user.id:
            return {
                "ok": False,
                "message": "Access denied",
                "error": "Unauthorized",
                "data": None,
            }

        await db.delete(item)
        await db.commit()

        return {
            "ok": True,
            "message": "Statement item deleted successfully",
            "error": None,
            "data": {"deleted_item_id": item_id},
        }

    except Exception as e:
        return {
            "ok": False,
            "message": "Failed to delete statement item",
            "error": str(e),
            "data": None,
        }
