from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select, delete
from sqlalchemy.orm import selectinload
from sqlalchemy.inspection import inspect as sa_inspect

from . import models
from . import schemas

from ..invoices import crud as invoices_crud
from ..user_docs.models import UserDocs
from ...utils.r2 import s3, R2_BUCKET


def infer_vat_registered(trn: str | None) -> bool:
    return bool(trn and trn.strip())


def vat_category_from_rate(rate: float) -> str:
    return "S" if rate == 5 else "Z"


def normalize_vat(v):
    """
    Map VAT codes to numeric:
    - S -> 5
    - Z/E/O -> 0
    - numeric strings/numbers -> float value
    Defaults to 0 on unknown.
    """
    if v is None:
        return 0
    if isinstance(v, str):
        code = v.strip().upper()
        if code == "S":
            return 5
        if code in {"Z", "E", "O"}:
            return 0
        try:
            return float(code)
        except Exception:
            return 0
    try:
        return float(v)
    except Exception:
        return 0


# ------------------------
# PRODUCTS
# ------------------------


async def list_products(db, owner_id):
    res = await db.execute(
        select(models.SalesProduct)
        .where(models.SalesProduct.owner_id == owner_id)
        .order_by(models.SalesProduct.id.desc())
    )
    return res.scalars().all()


async def add_product(db, owner_id, payload: list[schemas.ProductCreate]):
    created = []

    for p in payload:
        product = models.SalesProduct(
            owner_id=owner_id,
            name=p.name,
            unique_code=p.unique_code,
            vat_percentage=normalize_vat(p.vat_percentage),
            without_vat=p.without_vat or False,
        )
        db.add(product)
        created.append(product)
        await db.flush()

        inv = models.SalesInventoryItem(
            owner_id=owner_id,
            product_id=product.id,
            product_name=product.name,
            unique_code=product.unique_code,
            cost_price=None,
            selling_price=None,
            quantity=0,
        )
        db.add(inv)

    await db.commit()
    return created


async def edit_product(db, owner_id, pid, payload):
    res = await db.execute(
        select(models.SalesProduct).where(
            models.SalesProduct.owner_id == owner_id,
            models.SalesProduct.id == pid,
        )
    )
    product = res.scalar_one_or_none()
    if not product:
        return None

    for k, v in payload.dict(exclude_unset=True).items():
        if k == "vat_percentage":
            setattr(product, k, normalize_vat(v))
        else:
            setattr(product, k, v)

    inv_res = await db.execute(
        select(models.SalesInventoryItem).where(
            models.SalesInventoryItem.owner_id == owner_id,
            models.SalesInventoryItem.product_id == product.id,
        )
    )
    inv = inv_res.scalar_one_or_none()
    if inv:
        inv.product_name = product.name

    await db.commit()
    return product


async def delete_product(db, owner_id, pid):
    res = await db.execute(
        select(models.SalesProduct).where(
            models.SalesProduct.owner_id == owner_id,
            models.SalesProduct.id == pid,
        )
    )
    product = res.scalar_one_or_none()
    if not product:
        return False

    await db.execute(
        delete(models.SalesInventoryItem).where(
            models.SalesInventoryItem.owner_id == owner_id,
            models.SalesInventoryItem.product_id == pid,
        )
    )
    await db.flush()

    await db.delete(product)
    await db.commit()
    return True


# ------------------------
# CUSTOMERS
# ------------------------


async def list_customers(db, owner_id):
    res = await db.execute(
        select(models.SalesCustomer)
        .where(models.SalesCustomer.owner_id == owner_id)
        .order_by(models.SalesCustomer.id.desc())
    )
    return res.scalars().all()


async def add_customer(db, owner_id, payload: list[schemas.CustomerCreate]):
    created = []

    for c in payload:
        is_vat_registered = (
            c.is_vat_registered
            if c.is_vat_registered is not None
            else infer_vat_registered(c.trn)
        )

        obj = models.SalesCustomer(
            owner_id=owner_id,
            name=c.name,
            customer_code=c.customer_code,
            trn=c.trn,
            is_vat_registered=is_vat_registered,
            address_line_1=c.address_line_1,
            city=c.city,
            emirate=c.emirate,
            country_code=c.country_code or "AE",
            postal_code=c.postal_code,
            registered_address=c.registered_address,
            email=c.email,
            phone=c.phone,
            peppol_participant_id=c.peppol_participant_id,
            external_ref=c.external_ref,
        )

        db.add(obj)
        created.append(obj)

    await db.commit()
    return created


async def edit_customer(db, owner_id, cid, payload):
    res = await db.execute(
        select(models.SalesCustomer).where(
            models.SalesCustomer.owner_id == owner_id,
            models.SalesCustomer.id == cid,
        )
    )
    customer = res.scalar_one_or_none()
    if not customer:
        return None

    data = payload.dict(exclude_unset=True)

    if "trn" in data and "is_vat_registered" not in data:
        data["is_vat_registered"] = infer_vat_registered(data.get("trn"))

    for field, value in data.items():
        setattr(customer, field, value)

    await db.commit()
    return customer


async def delete_customer(db, owner_id, cid):
    res = await db.execute(
        select(models.SalesCustomer).where(
            models.SalesCustomer.owner_id == owner_id,
            models.SalesCustomer.id == cid,
        )
    )
    customer = res.scalar_one_or_none()
    if not customer:
        return False

    if customer.logo_r2_key:
        try:
            s3.delete_object(Bucket=R2_BUCKET, Key=customer.logo_r2_key)
        except Exception:
            pass

    await db.delete(customer)
    await db.commit()
    return True


# ------------------------
# INVOICE HELPERS
# ------------------------


def compute_line_item_totals(items):
    enriched = []
    subtotal = 0
    vat_total = 0.0
    tax_map = {}

    for item in items:
        base = item.unit_cost * item.quantity
        discount = item.discount or 0
        net = max(base - discount, 0)

        vat_pct = normalize_vat(item.vat_percentage)
        vat_amount = round(net * (vat_pct / 100), 2)
        category = vat_category_from_rate(vat_pct)

        enriched.append(
            {
                "product_id": item.product_id,
                "name": item.name,
                "description": item.description,
                "quantity": item.quantity,
                "unit_cost": item.unit_cost,
                "vat_percentage": vat_pct,
                "discount": item.discount,
                "line_total": round(net + vat_amount, 2),
            }
        )

        subtotal += net
        vat_total += vat_amount

        tax_map.setdefault(category, {"rate": vat_pct, "taxable": 0, "vat": 0})
        tax_map[category]["taxable"] += net
        tax_map[category]["vat"] += vat_amount

        tax_summary = {
            "categories": [
                {
                    "vat_rate": v["rate"],
                    "taxable_amount": round(v["taxable"], 2),
                    "vat_amount": round(v["vat"], 2),
                    "category_code": k,
                }
                for k, v in tax_map.items()
            ],
            "total_vat": round(vat_total, 2),
        }

    return {
        "subtotal": round(subtotal, 2),
        "vat": round(vat_total, 2),
        "tax_summary": tax_summary,
        "line_items": enriched,
    }


def _prepare_initial_payment(payload, invoice_total: float):
    if not getattr(payload, "paid_in_advance", False):
        return 0.0, None, []

    amount = float(getattr(payload, "advance_amount", 0) or 0)
    if amount <= 0:
        return 0.0, None, []

    applied = min(amount, float(invoice_total))
    if applied <= 0:
        return 0.0, None, []

    paid_at = getattr(payload, "advance_paid_at", None) or datetime.utcnow()
    note = getattr(payload, "advance_note", None)

    return (
        round(applied, 2),
        paid_at,
        [{"amount": round(applied, 2), "paid_at": paid_at.isoformat(), "note": note}],
    )


def serialize_invoice(invoice: models.SalesInvoice):
    invoice_mapper = sa_inspect(models.SalesInvoice)
    data = {c.key: getattr(invoice, c.key) for c in invoice_mapper.columns}

    line_mapper = sa_inspect(models.SalesInvoiceLineItem)
    product_mapper = sa_inspect(models.SalesProduct)

    data["line_items"] = []
    for item in invoice.line_items or []:
        item_dict = {c.key: getattr(item, c.key) for c in line_mapper.columns}
        if item.product:
            item_dict["product"] = {
                c.key: getattr(item.product, c.key) for c in product_mapper.columns
            }
        else:
            item_dict["product"] = None
        data["line_items"].append(item_dict)

    total = float(data.get("total") or 0)
    paid = float(data.get("amount_paid") or 0)

    data["amount_due"] = round(max(total - paid, 0), 2)

    if paid >= total and total > 0:
        status = "paid"
    elif paid > 0:
        status = "partial"
    else:
        status = "unpaid"

    data["payment_status"] = status
    data["payment_events"] = data.get("payment_events") or []

    due = data.get("due_date")
    if due and status != "paid":
        now = datetime.utcnow().date()
        overdue = now > due.date()
        data["is_overdue"] = overdue
        data["overdue_days"] = (now - due.date()).days if overdue else 0
    else:
        data["is_overdue"] = False
        data["overdue_days"] = 0

    return data


# ------------------------
# INVOICES
# ------------------------


async def create_invoice(db, owner_id, payload: schemas.SalesInvoiceCreate):
    # -------------------------
    # Defaults (AUTHORITATIVE)
    # -------------------------
    invoice_date = payload.invoice_date or datetime.utcnow()
    supply_date = payload.supply_date or invoice_date
    invoice_type = payload.invoice_type or "TAX_INVOICE"
    currency = payload.currency or "AED"

    # -------------------------
    # Seller document resolution
    # -------------------------
    doc = None
    if payload.seller_doc_id is not None:
        res = await db.execute(
            select(UserDocs).where(
                UserDocs.user_id == owner_id,
                UserDocs.id == payload.seller_doc_id,
            )
        )
        doc = res.scalar_one_or_none()
    else:
        res = await db.execute(
            select(UserDocs)
            .where(
                UserDocs.user_id == owner_id,
                UserDocs.file_name.in_(["vat_certificate", "ct_certificate"]),
            )
            .order_by(UserDocs.updated_at.desc())
        )
        doc = res.scalars().first()

    company_name = company_name_ar = company_address = company_trn = None

    if doc:
        if doc.doc_type == "vat_certificate":
            company_name = doc.vat_legal_name_english or doc.legal_name
            company_name_ar = doc.vat_legal_name_arabic
            company_address = doc.vat_registered_address or doc.company_address
            company_trn = doc.vat_tax_registration_number
        elif doc.doc_type == "ct_certificate":
            company_name = doc.ct_legal_name_en or doc.legal_name
            company_name_ar = doc.ct_legal_name_ar
            company_address = doc.ct_registered_address or doc.company_address
            company_trn = doc.ct_trn
    else:
        company_name = payload.manual_seller_company_en or ""
        company_name_ar = payload.manual_seller_company_ar
        company_address = payload.manual_seller_address
        company_trn = payload.manual_seller_trn or ""

    if not company_name or not company_trn:
        return None

    # -------------------------
    # Buyer + invoice basics
    # -------------------------
    if not payload.customer_name:
        payload.customer_name = "Cash Customer"

    if not payload.invoice_number:
        payload.invoice_number = await get_next_invoice_number(db, owner_id)

    terms_obj = await get_terms(db, owner_id)
    terms_text = terms_obj.terms if terms_obj else ""

    # =========================================================
    # MANUAL INVOICE (no line items from UI)
    # =========================================================
    if not payload.line_items:
        total = round(float(payload.total or 0), 2)
        vat_pct = normalize_vat(getattr(payload, "manual_vat_percentage", 5))

        # Correct VAT math
        subtotal = round(total / (1 + vat_pct / 100), 2)
        vat = round(total - subtotal, 2)

        discount = payload.discount or 0
        due_date = payload.due_date or datetime.utcnow()
        paid, paid_at, events = _prepare_initial_payment(payload, total)

        inv = models.SalesInvoice(
            owner_id=owner_id,
            company_name=company_name,
            company_name_arabic=company_name_ar,
            company_address=company_address,
            company_trn=company_trn,
            customer_id=payload.customer_id,
            customer_name=payload.customer_name,
            customer_trn=payload.customer_trn,
            invoice_number=payload.invoice_number,
            invoice_type=invoice_type,
            currency=currency,
            invoice_date=invoice_date,
            supply_date=supply_date,
            due_date=due_date,
            notes=payload.notes,
            terms_and_conditions=terms_text,
            discount=discount,
            tax_summary={
                "categories": [
                    {
                        "vat_rate": vat_pct,
                        "taxable_amount": subtotal,
                        "vat_amount": vat,
                        "category_code": vat_category_from_rate(vat_pct),
                    }
                ],
                "total_vat": vat,
            },
            subtotal=subtotal,
            total_vat=vat,
            total=total,
            amount_paid=paid,
            last_payment_at=paid_at,
            payment_events=events or None,
        )

        db.add(inv)
        await db.commit()
        await db.refresh(inv)

        # Single synthetic line item (gross = line_total)
        db.add(
            models.SalesInvoiceLineItem(
                invoice_id=inv.id,
                name="Standard Rated Supplies",
                description="Standard Rated Supplies",
                quantity=1,
                unit_cost=subtotal,
                vat_percentage=vat_pct,
                discount=0,
                line_total=total,  # tax-inclusive
            )
        )
        await db.commit()

        await invoices_crud.create_invoice_from_sales(db, owner_id, inv)
        return inv

    # =========================================================
    # PRODUCT LINE INVOICE
    # =========================================================
    for li in payload.line_items:
        if li.product_id:
            res = await db.execute(
                select(models.SalesInventoryItem).where(
                    models.SalesInventoryItem.owner_id == owner_id,
                    models.SalesInventoryItem.product_id == li.product_id,
                )
            )
            inv_item = res.scalar_one_or_none()
            if inv_item and inv_item.selling_price is not None:
                li.unit_cost = inv_item.selling_price

        li.vat_percentage = normalize_vat(li.vat_percentage)

    totals = compute_line_item_totals(payload.line_items)

    discount = payload.discount or 0
    total = round(totals["subtotal"] + totals["vat"] - discount, 2)

    due_date = payload.due_date or datetime.utcnow()
    paid, paid_at, events = _prepare_initial_payment(payload, total)

    inv = models.SalesInvoice(
        owner_id=owner_id,
        company_name=company_name,
        company_name_arabic=company_name_ar,
        company_address=company_address,
        company_trn=company_trn,
        customer_id=payload.customer_id,
        customer_name=payload.customer_name,
        customer_trn=payload.customer_trn,
        invoice_number=payload.invoice_number,
        invoice_type=invoice_type,
        currency=currency,
        invoice_date=invoice_date,
        supply_date=supply_date,
        due_date=due_date,
        notes=payload.notes,
        terms_and_conditions=terms_text,
        discount=discount,
        tax_summary=totals["tax_summary"],
        subtotal=totals["subtotal"],
        total_vat=totals["vat"],
        total=total,
        amount_paid=paid,
        last_payment_at=paid_at,
        payment_events=events or None,
    )

    db.add(inv)
    await db.commit()
    await db.refresh(inv)

    for li in totals["line_items"]:
        db.add(models.SalesInvoiceLineItem(invoice_id=inv.id, **li))

    await db.commit()

    await invoices_crud.create_invoice_from_sales(db, owner_id, inv)
    await adjust_inventory_for_invoice(db, owner_id, totals["line_items"])

    return inv


async def list_invoices(db, owner_id, limit=1000, offset=0):
    res = await db.execute(
        select(models.SalesInvoice)
        .options(
            selectinload(models.SalesInvoice.line_items).selectinload(
                models.SalesInvoiceLineItem.product
            )
        )
        .where(
            models.SalesInvoice.owner_id == owner_id,
            models.SalesInvoice.is_deleted == False,
        )
        .order_by(models.SalesInvoice.id.desc())
        .limit(limit)
        .offset(offset)
    )
    invoices = res.scalars().unique().all()
    return [serialize_invoice(inv) for inv in invoices]


async def delete_invoice(db, owner_id, invoice_id):
    res = await db.execute(
        select(models.SalesInvoice).where(
            models.SalesInvoice.owner_id == owner_id,
            models.SalesInvoice.id == invoice_id,
        )
    )
    inv = res.scalar_one_or_none()
    if not inv:
        return False

    inv.is_deleted = True

    if inv.file_path:
        try:
            s3.delete_object(Bucket=R2_BUCKET, Key=inv.file_path.split("r2.dev/")[-1])
        except Exception:
            pass

    await db.commit()
    return True


async def record_payment(db, owner_id, invoice_id, payload: schemas.SalesPaymentCreate):
    invoice = await get_invoice_with_items(db, owner_id, invoice_id)
    if not invoice:
        return None, "Invoice not found"

    amount = float(payload.amount or 0)
    if amount <= 0:
        return None, "Invalid amount"

    remaining = max((invoice.total or 0) - (invoice.amount_paid or 0), 0)
    applied = min(amount, remaining)

    events = invoice.payment_events or []
    events.append(
        {
            "amount": round(applied, 2),
            "paid_at": (payload.paid_at or datetime.utcnow()).isoformat(),
            "note": payload.note,
        }
    )

    invoice.amount_paid = round((invoice.amount_paid or 0) + applied, 2)
    invoice.last_payment_at = payload.paid_at or datetime.utcnow()
    invoice.payment_events = events

    await db.commit()
    await db.refresh(invoice)

    return serialize_invoice(invoice), None


# ------------------------
# INVENTORY + TERMS
# ------------------------


async def adjust_inventory_for_invoice(db, owner_id: int, line_items: list[dict]):
    for li in line_items:
        pid = li.get("product_id")
        qty = li.get("quantity") or 0
        if not pid or qty <= 0:
            continue

        res = await db.execute(
            select(models.SalesInventoryItem).where(
                models.SalesInventoryItem.owner_id == owner_id,
                models.SalesInventoryItem.product_id == pid,
            )
        )
        inv = res.scalar_one_or_none()
        if inv:
            inv.quantity = max((inv.quantity or 0) - qty, 0)

    await db.commit()


async def add_inventory_items(
    db,
    owner_id: int,
    payload: list[schemas.InventoryItemCreate],
):
    created_or_updated = []

    for item in payload:
        product = None

        if item.product_id is not None:
            res = await db.execute(
                select(models.SalesProduct).where(
                    models.SalesProduct.id == item.product_id,
                    models.SalesProduct.owner_id == owner_id,
                )
            )
            product = res.scalar_one_or_none()

        if product is None:
            res = await db.execute(
                select(models.SalesProduct).where(
                    models.SalesProduct.owner_id == owner_id,
                    models.SalesProduct.unique_code == item.unique_code,
                )
            )
            product = res.scalar_one_or_none()

        if product is None and item.product_name:
            res = await db.execute(
                select(models.SalesProduct).where(
                    models.SalesProduct.owner_id == owner_id,
                    models.SalesProduct.name == item.product_name,
                )
            )
            product = res.scalar_one_or_none()

        if product is None:
            cost = item.cost_price or 0
            cost_dec = Decimal(str(cost))
            total_dec = cost_dec.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

            product = models.SalesProduct(
                owner_id=owner_id,
                name=item.product_name or item.unique_code,
                unique_code=item.unique_code,
                vat_percentage=0,
                without_vat=True,
                total_cost=float(total_dec),
            )
            db.add(product)
            await db.flush()

        product_name = item.product_name or product.name

        res = await db.execute(
            select(models.SalesInventoryItem).where(
                models.SalesInventoryItem.owner_id == owner_id,
                models.SalesInventoryItem.unique_code == item.unique_code,
            )
        )
        inv = res.scalar_one_or_none()

        if inv:
            inv.product_id = product.id
            inv.product_name = product_name
            if item.cost_price is not None:
                inv.cost_price = item.cost_price
            if item.selling_price is not None:
                inv.selling_price = item.selling_price
            inv.quantity = (inv.quantity or 0) + (item.quantity or 0)
        else:
            inv = models.SalesInventoryItem(
                owner_id=owner_id,
                product_id=product.id,
                product_name=product_name,
                unique_code=item.unique_code,
                cost_price=item.cost_price,
                selling_price=item.selling_price,
                quantity=item.quantity,
            )
            db.add(inv)

        created_or_updated.append(inv)

    await db.commit()
    return created_or_updated


async def sync_products_to_inventory(db, owner_id):
    res = await db.execute(
        select(models.SalesProduct).where(models.SalesProduct.owner_id == owner_id)
    )
    products = res.scalars().all()

    inv_res = await db.execute(
        select(models.SalesInventoryItem).where(
            models.SalesInventoryItem.owner_id == owner_id
        )
    )
    inventory = {inv.product_id: inv for inv in inv_res.scalars().all()}

    for p in products:
        if p.id not in inventory:
            inv = models.SalesInventoryItem(
                owner_id=owner_id,
                product_id=p.id,
                product_name=p.name,
                unique_code=p.unique_code,
                cost_price=p.cost_per_unit,
                selling_price=None,
                quantity=0,
            )
            db.add(inv)

    await db.commit()


async def list_inventory(db, owner_id):
    await sync_products_to_inventory(db, owner_id)
    res = await db.execute(
        select(models.SalesInventoryItem)
        .where(models.SalesInventoryItem.owner_id == owner_id)
        .order_by(models.SalesInventoryItem.id.desc())
    )
    return res.scalars().all()


async def get_invoice_with_items(db, owner_id, invoice_id):
    res = await db.execute(
        select(models.SalesInvoice)
        .options(
            selectinload(models.SalesInvoice.line_items).selectinload(
                models.SalesInvoiceLineItem.product
            )
        )
        .where(
            models.SalesInvoice.id == invoice_id,
            models.SalesInvoice.owner_id == owner_id,
            models.SalesInvoice.is_deleted == False,
        )
    )
    return res.scalar_one_or_none()


async def get_terms(db, owner_id):
    res = await db.execute(
        select(models.SalesTerms).where(models.SalesTerms.owner_id == owner_id)
    )
    return res.scalar_one_or_none()


async def update_terms(db, owner_id, payload: schemas.SalesTermsUpdate):
    existing = await get_terms(db, owner_id)
    if existing:
        existing.terms = payload.terms
        await db.commit()
        return existing

    obj = models.SalesTerms(owner_id=owner_id, terms=payload.terms)
    db.add(obj)
    await db.commit()
    return obj


def number_to_words(n):
    from num2words import num2words

    return num2words(n, lang="en").title()


async def get_next_invoice_number(db, owner_id):
    today = datetime.now().strftime("%Y/%m/%d")
    prefix = f"{today}-"

    res = await db.execute(
        select(models.SalesInvoice.invoice_number)
        .where(
            models.SalesInvoice.owner_id == owner_id,
            models.SalesInvoice.invoice_number.like(f"{prefix}%"),
        )
        .order_by(models.SalesInvoice.invoice_number.desc())
        .limit(1)
    )

    last = res.scalar_one_or_none()
    if not last:
        return f"{prefix}001"

    try:
        num = int(last.split("-")[-1])
    except Exception:
        num = 0

    return f"{prefix}{num + 1:03d}"


def _serialize_tax_credit_note(note: models.SalesTaxCreditNote):
    items = []
    for li in note.line_items or []:
        items.append(
            {
                "id": li.id,
                "product_id": li.product_id,
                "name": li.name,
                "description": li.description,
                "quantity": li.quantity,
                "unit_cost": li.unit_cost,
                "vat_percentage": li.vat_percentage,
                "discount": li.discount,
                "line_total": li.line_total,
                "product": (
                    {
                        "id": li.product.id,
                        "name": li.product.name,
                        "unique_code": li.product.unique_code,
                    }
                    if li.product
                    else None
                ),
            }
        )

    return {
        "id": note.id,
        "credit_note_number": note.credit_note_number,
        "credit_note_date": note.credit_note_date,
        "reference_invoice_id": note.reference_invoice_id,
        "customer_name": note.customer_name,
        "customer_trn": note.customer_trn,
        "notes": note.notes,
        "subtotal": note.subtotal,
        "total_vat": note.total_vat,
        "total": note.total,
        "line_items": items,
        "created_at": note.created_at,
        "updated_at": note.updated_at,
    }


async def get_next_credit_note_number(db, owner_id: int):
    today = datetime.now().strftime("%Y/%m/%d")
    prefix = f"CN-{today}-"

    res = await db.execute(
        select(models.SalesTaxCreditNote.credit_note_number)
        .where(
            models.SalesTaxCreditNote.owner_id == owner_id,
            models.SalesTaxCreditNote.credit_note_number.like(f"{prefix}%"),
        )
        .order_by(models.SalesTaxCreditNote.credit_note_number.desc())
        .limit(1)
    )

    last = res.scalar_one_or_none()
    if not last:
        return f"{prefix}001"

    try:
        num = int(last.split("-")[-1])
    except Exception:
        num = 0

    return f"{prefix}{num + 1:03d}"


async def create_tax_credit_note(
    db,
    owner_id: int,
    invoice_id: int,
    payload: schemas.TaxCreditNoteCreate,
):
    inv = await get_invoice_with_items(db, owner_id, invoice_id)
    if not inv:
        return None, "Invoice not found"

    if not payload.line_items:
        return None, "At least one line item is required"

    credit_note_number = (
        payload.credit_note_number or await get_next_credit_note_number(db, owner_id)
    )

    invoice_line_by_id = {li.id: li for li in inv.line_items or []}
    credit_lines = []

    for item in payload.line_items:
        src = invoice_line_by_id.get(item.invoice_line_item_id)
        if not src:
            return None, "Invalid invoice_line_item_id"

        qty = float(item.quantity or 0)
        if qty <= 0:
            return None, "Quantity must be > 0"

        credit_lines.append(
            {
                "product_id": src.product_id,
                "name": src.name,
                "description": src.description,
                "quantity": qty,
                "unit_cost": float(src.unit_cost),
                "vat_percentage": normalize_vat(src.vat_percentage),
                "discount": 0,
            }
        )

    line_models = [schemas.SalesLineItemCreate(**li) for li in credit_lines]
    totals = compute_line_item_totals(line_models)
    subtotal = totals["subtotal"]
    vat = totals["vat"]
    total = round(subtotal + vat, 2)

    note = models.SalesTaxCreditNote(
        owner_id=owner_id,
        reference_invoice_id=inv.id,
        credit_note_number=credit_note_number,
        credit_note_date=payload.credit_note_date or datetime.utcnow(),
        customer_name=inv.customer_name,
        customer_trn=inv.customer_trn,
        notes=payload.notes,
        subtotal=-abs(subtotal),
        total_vat=-abs(vat),
        total=-abs(total),
    )

    db.add(note)
    await db.commit()
    await db.refresh(note)

    for li in totals["line_items"]:
        line_total = float(li["line_total"])
        db.add(
            models.SalesTaxCreditNoteLineItem(
                credit_note_id=note.id,
                product_id=li["product_id"],
                name=li["name"],
                description=li["description"],
                quantity=li["quantity"],
                unit_cost=li["unit_cost"],
                vat_percentage=normalize_vat(li["vat_percentage"]),
                discount=li.get("discount"),
                line_total=-abs(line_total),
            )
        )

    await db.commit()

    res = await db.execute(
        select(models.SalesTaxCreditNote)
        .options(
            selectinload(models.SalesTaxCreditNote.line_items).selectinload(
                models.SalesTaxCreditNoteLineItem.product
            )
        )
        .where(models.SalesTaxCreditNote.id == note.id)
    )
    full = res.scalar_one()
    return _serialize_tax_credit_note(full), None


async def list_tax_credit_notes(db, owner_id: int, limit: int = 1000, offset: int = 0):
    res = await db.execute(
        select(models.SalesTaxCreditNote)
        .options(
            selectinload(models.SalesTaxCreditNote.line_items).selectinload(
                models.SalesTaxCreditNoteLineItem.product
            )
        )
        .where(models.SalesTaxCreditNote.owner_id == owner_id)
        .order_by(models.SalesTaxCreditNote.id.desc())
        .limit(limit)
        .offset(offset)
    )
    notes = res.scalars().unique().all()
    return [_serialize_tax_credit_note(n) for n in notes]


async def edit_inventory_item(
    db, owner_id: int, iid: int, payload: schemas.InventoryItemEdit
):
    res = await db.execute(
        select(models.SalesInventoryItem).where(
            models.SalesInventoryItem.owner_id == owner_id,
            models.SalesInventoryItem.id == iid,
        )
    )
    inv = res.scalar_one_or_none()
    if not inv:
        return None

    data = payload.dict(exclude_unset=True)

    if "unique_code" in data:
        data.pop("unique_code")

    if "product_id" in data and data["product_id"] is not None:
        pres = await db.execute(
            select(models.SalesProduct).where(
                models.SalesProduct.id == data["product_id"],
                models.SalesProduct.owner_id == owner_id,
            )
        )
        product = pres.scalar_one_or_none()
        if product:
            inv.product_id = product.id
            if "product_name" not in data:
                inv.product_name = product.name

    for field, value in data.items():
        if field == "product_id":
            continue
        if field == "quantity":
            if value is None:
                continue

        setattr(inv, field, value)

    await db.commit()
    return inv


async def adjust_inventory_quantity(db, owner_id: int, product_id: int, delta: float):
    res = await db.execute(
        select(models.SalesInventoryItem).where(
            models.SalesInventoryItem.owner_id == owner_id,
            models.SalesInventoryItem.product_id == product_id,
        )
    )
    inv = res.scalar_one_or_none()

    if not inv:
        return None

    inv.quantity = max((inv.quantity or 0) + delta, 0)

    await db.commit()
    return inv
