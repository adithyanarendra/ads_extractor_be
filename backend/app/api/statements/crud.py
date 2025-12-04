import os
from uuid import uuid4
import json
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, cast, Float

from .models import Statement, StatementItem, Account
from ...utils.r2 import upload_to_r2_bytes, get_file_from_r2
from .service import parse_statement
from ...core.database import SessionLocal
from .reconcile_service import reconcile_statement_with_invoices


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
        file_key = f"statements/{user.effective_user_id}/{uuid4()}{file_ext}"
        file_url = upload_to_r2_bytes(file_bytes, file_key)

        stmt = Statement(
            owner_id=user.effective_user_id,
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

            account_number = parsed.get("account_number")
            provider = parsed.get("provider")

            if account_number:
                result = await db.execute(
                    select(Account).where(
                        Account.owner_id == stmt.owner_id,
                        Account.account_number == account_number,
                    )
                )
                account = result.scalars().first()

                if not account:
                    account = Account(
                        owner_id=stmt.owner_id,
                        account_number=account_number,
                        provider=provider,
                    )
                    db.add(account)
                    await db.flush()

                stmt.account_id = account.id
            transactions = parsed.get("transactions", [])

            for tx in transactions:
                if tx.get("transaction_type") == "credit":
                    from_ac = tx.get("from_account") or "Payment A/C"
                    to_ac = tx.get("to_account") or "Bank"
                else:
                    from_ac = tx.get("from_account") or "Bank"
                    to_ac = tx.get("to_account") or "Payment A/C"

                db.add(
                    StatementItem(
                        statement_id=statement_id,
                        transaction_id=tx.get("transaction_id"),
                        transaction_date=tx.get("date"),
                        description=tx.get("description"),
                        transaction_type=tx.get("transaction_type"),
                        amount=tx.get("amount"),
                        balance=tx.get("balance"),
                        transaction_type_detail=tx.get("transaction_type_detail"),
                        remarks=tx.get("remarks"),
                        from_account=from_ac,
                        to_account=to_ac,
                    )
                )

            await db.commit()
            await reconcile_statement_with_invoices(db, stmt.owner_id, statement_id)

            print(f"✅ Background parsing completed for statement {statement_id}")

        except Exception as e:
            print("❌ Background parsing failed:", e)


async def list_statements(db: AsyncSession, user):
    try:
        result = await db.execute(
            select(Statement).where(Statement.owner_id == user.effective_user_id)
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
            .where(Statement.owner_id == user.effective_user_id)
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


async def list_accounts(db: AsyncSession, user):
    try:
        result = await db.execute(
            select(Account).where(Account.owner_id == user.effective_user_id)
        )
        accounts = result.scalars().all()

        cleaned = [
            {
                "id": a.id,
                "account_number": a.account_number,
                "provider": a.provider,
                "created_at": a.created_at,
            }
            for a in accounts
        ]

        return {
            "ok": True,
            "message": "Accounts retrieved",
            "error": None,
            "data": cleaned,
        }

    except Exception as e:
        return {
            "ok": False,
            "message": "Failed to list accounts",
            "error": str(e),
            "data": None,
        }


async def get_statement(db: AsyncSession, statement_id: int, user):
    try:
        stmt = await db.get(Statement, statement_id)

        if not stmt or stmt.owner_id != user.effective_user_id:
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

        if not stmt or stmt.owner_id != user.effective_user_id:
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
        if not stmt or stmt.owner_id != user.effective_user_id:
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


async def delete_account(db: AsyncSession, account_id: int, user):
    try:
        account = await db.get(Account, account_id)

        if not account or account.owner_id != user.effective_user_id:
            return {
                "ok": False,
                "message": "Account not found or access denied",
                "error": "Unauthorized or missing",
                "data": None,
            }

        result = await db.execute(
            select(Statement).where(Statement.account_id == account.id)
        )
        stmts = result.scalars().all()

        for stmt in stmts:
            await db.delete(stmt)

        await db.delete(account)
        await db.commit()

        return {
            "ok": True,
            "message": "Account deleted successfully",
            "error": None,
            "data": {"deleted_account_id": account_id},
        }

    except Exception as e:
        return {
            "ok": False,
            "message": "Failed to delete account",
            "error": str(e),
            "data": None,
        }


async def update_statement_item(db: AsyncSession, item_id: int, user, updates: dict):
    try:
        item = await db.get(StatementItem, item_id)
        if not item:
            return {
                "ok": False,
                "message": "Statement item not found",
                "error": "Missing",
                "data": None,
            }

        stmt = await db.get(Statement, item.statement_id)
        if not stmt or stmt.owner_id != user.effective_user_id:
            return {
                "ok": False,
                "message": "Access denied",
                "error": "Unauthorized",
                "data": None,
            }

        restricted = {"id", "statement_id"}
        for key in restricted:
            if key in updates:
                updates.pop(key)

        model_fields = {c.name for c in StatementItem.__table__.columns}

        for key, value in updates.items():
            if key in model_fields:
                setattr(item, key, value)

        await db.commit()
        await db.refresh(item)

        return {
            "ok": True,
            "message": "Statement item updated",
            "error": None,
            "data": item,
        }

    except Exception as e:
        return {
            "ok": False,
            "message": "Failed to update statement item",
            "error": str(e),
            "data": None,
        }


async def get_statement_analytics(db: AsyncSession, user):
    try:
        stmt = (
            select(
                StatementItem.transaction_type,
                func.sum(cast(StatementItem.amount, Float)).label("total"),
            )
            .join(Statement, StatementItem.statement_id == Statement.id)
            .where(Statement.owner_id == user.effective_user_id)
            .group_by(StatementItem.transaction_type)
        )

        result = await db.execute(stmt)
        rows = result.all()

        total_revenue = 0.0
        total_expense = 0.0

        for row in rows:
            tx_type, total = row
            if tx_type == "credit":
                total_revenue = total or 0.0
            elif tx_type == "debit":
                total_expense = total or 0.0

        net_profit = (total_revenue or 0) - (total_expense or 0)

        return {
            "ok": True,
            "message": "Analytics generated",
            "error": None,
            "data": {
                "total_revenue": round(total_revenue, 2),
                "total_expense": round(total_expense, 2),
                "net_profit": round(net_profit, 2),
            },
        }

    except Exception as e:
        return {
            "ok": False,
            "message": "Failed to calculate analytics",
            "error": str(e),
            "data": None,
        }
