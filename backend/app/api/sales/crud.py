from datetime import datetime
from sqlalchemy import select, delete
from sqlalchemy.orm import selectinload
from decimal import Decimal, ROUND_HALF_UP


from . import models
from . import schemas

from ..user_docs.models import UserDocs
from ...utils.r2 import s3, R2_BUCKET


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
            vat_percentage=p.vat_percentage or 0,
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
    result = await db.execute(
        select(models.SalesProduct).where(
            models.SalesProduct.owner_id == owner_id, models.SalesProduct.id == pid
        )
    )
    p = result.scalar_one_or_none()
    if not p:
        return None

    for k, v in payload.dict(exclude_unset=True).items():
        setattr(p, k, v)

    res = await db.execute(
        select(models.SalesInventoryItem).where(
            models.SalesInventoryItem.product_id == p.id,
            models.SalesInventoryItem.owner_id == owner_id,
        )
    )

    inv = res.scalar_one_or_none()
    if inv:
        inv.product_name = p.name
    await db.commit()
    return p


async def delete_product(db, owner_id, pid):
    res = await db.execute(
        select(models.SalesProduct).where(
            models.SalesProduct.owner_id == owner_id, models.SalesProduct.id == pid
        )
    )
    p = res.scalar_one_or_none()
    if not p:
        return False

    await db.execute(
        delete(models.SalesInventoryItem).where(
            models.SalesInventoryItem.owner_id == owner_id,
            models.SalesInventoryItem.product_id == pid,
        )
    )

    await db.flush()

    # Now delete product
    await db.delete(p)
    await db.commit()

    return True


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
        obj = models.SalesCustomer(
            owner_id=owner_id,
            name=c.name,
            trn=c.trn,
            registered_address=c.registered_address,
        )
        db.add(obj)
        created.append(obj)

    await db.commit()
    return created


async def edit_customer(db, owner_id, cid, payload):
    result = await db.execute(
        select(models.SalesCustomer).where(
            models.SalesCustomer.owner_id == owner_id, models.SalesCustomer.id == cid
        )
    )
    c = result.scalar_one_or_none()
    if not c:
        return None

    for k, v in payload.dict(exclude_unset=True).items():
        setattr(c, k, v)

    await db.commit()
    return c


async def delete_customer(db, owner_id, cid):
    result = await db.execute(
        select(models.SalesCustomer).where(
            models.SalesCustomer.owner_id == owner_id, models.SalesCustomer.id == cid
        )
    )
    c = result.scalar_one_or_none()
    if not c:
        return False

    if c.logo_r2_key:
        try:
            s3.delete_object(Bucket=R2_BUCKET, Key=c.logo_r2_key)
        except:
            pass

    await db.delete(c)
    await db.commit()
    return True


def compute_line_item_totals(items):
    enriched = []
    subtotal = 0
    vat = 0

    for item in items:
        base = item.unit_cost * item.quantity
        discount = item.discount or 0
        discounted = max(base - discount, 0)

        vat_amount = discounted * (item.vat_percentage / 100)
        total = discounted + vat_amount

        enriched.append(
            {
                "product_id": item.product_id,
                "name": item.name or item.description,
                "description": item.description,
                "quantity": item.quantity,
                "unit_cost": item.unit_cost,
                "vat_percentage": item.vat_percentage,
                "discount": item.discount,
                "line_total": round(total, 2),
            }
        )

        subtotal += base
        vat += vat_amount

    return {
        "subtotal": round(subtotal, 2),
        "vat": round(vat, 2),
        "line_items": enriched,
    }


async def create_invoice(db, owner_id, payload: schemas.SalesInvoiceCreate):
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

    company_name = None
    company_name_ar = None
    company_address = None
    company_trn = None

    if doc:
        if doc.file_name == "vat_certificate":
            company_name = doc.vat_legal_name_english or doc.legal_name
            company_name_ar = doc.vat_legal_name_arabic
            company_address = doc.vat_registered_address or doc.company_address
            company_trn = doc.vat_tax_registration_number

        elif doc.file_name == "ct_certificate":
            company_name = doc.ct_legal_name_en or doc.legal_name
            company_name_ar = doc.ct_legal_name_ar
            company_address = doc.ct_registered_address or doc.company_address
            company_trn = doc.ct_trn

    if not doc and (
        payload.manual_seller_company_en
        or payload.manual_seller_trn
        or payload.manual_seller_address
        or payload.manual_seller_company_ar
    ):
        company_name = payload.manual_seller_company_en or ""
        company_name_ar = payload.manual_seller_company_ar
        company_address = payload.manual_seller_address
        company_trn = payload.manual_seller_trn or ""

    if not company_name or not company_trn:
        return None

    if not payload.customer_name or payload.customer_name.strip() == "":
        payload.customer_name = "Cash Customer"

    if not payload.invoice_number:
        payload.invoice_number = await get_next_invoice_number(db, owner_id)

    terms_text = ""
    terms_obj = await get_terms(db, owner_id)
    if terms_obj:
        terms_text = terms_obj.terms

    if not payload.line_items or len(payload.line_items) == 0:
        manual_total = float(payload.total or 0)
        vat_percentage = float(getattr(payload, "manual_vat_percentage", 0) or 5)

        subtotal = manual_total / (1 + vat_percentage / 100)
        vat_amount = manual_total - subtotal

        if vat_percentage == 5:
            item_name = "Standard Rated Supplies"
        else:
            item_name = f"Supplies @ {vat_percentage}% VAT"

        inv = models.SalesInvoice(
            owner_id=owner_id,
            company_name=company_name or "",
            company_name_arabic=company_name_ar,
            company_trn=company_trn or "",
            company_address=company_address,
            customer_id=payload.customer_id,
            customer_name=payload.customer_name,
            customer_trn=payload.customer_trn,
            invoice_number=payload.invoice_number,
            notes=payload.notes,
            terms_and_conditions=terms_text,
            subtotal=round(subtotal, 2),
            total_vat=round(vat_amount, 2),
            discount=0,
            total=round(manual_total, 2),
        )
        db.add(inv)
        await db.commit()
        await db.refresh(inv)

        li = models.SalesInvoiceLineItem(
            invoice_id=inv.id,
            product_id=None,
            name=item_name,
            description=item_name,
            quantity=1,
            unit_cost=round(subtotal, 2),
            vat_percentage=vat_percentage,
            discount=0,
            line_total=round(manual_total, 2),
        )

        db.add(li)
        await db.commit()

        return inv

    for li in payload.line_items:
        if li.product_id:
            res = await db.execute(
                select(models.SalesInventoryItem).where(
                    models.SalesInventoryItem.owner_id == owner_id,
                    models.SalesInventoryItem.product_id == li.product_id,
                )
            )
            inv = res.scalar_one_or_none()
            if inv and inv.selling_price is not None:
                li.unit_cost = inv.selling_price

    totals = compute_line_item_totals(payload.line_items)
    invoice_discount = payload.discount or 0

    total_after_discount = totals["subtotal"] + totals["vat"] - invoice_discount

    inv = models.SalesInvoice(
        owner_id=owner_id,
        company_name=company_name or "",
        company_name_arabic=company_name_ar,
        company_trn=company_trn or "",
        company_address=company_address,
        customer_id=payload.customer_id,
        customer_name=payload.customer_name,
        customer_trn=payload.customer_trn,
        invoice_number=payload.invoice_number,
        notes=payload.notes,
        terms_and_conditions=terms_text,
        discount=invoice_discount,
        subtotal=totals["subtotal"],
        total_vat=totals["vat"],
        total=round(total_after_discount, 2),
    )

    db.add(inv)
    await db.commit()
    await db.refresh(inv)

    for li in totals["line_items"]:
        item = models.SalesInvoiceLineItem(invoice_id=inv.id, **li)
        db.add(item)

    await db.commit()
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
    return res.scalars().all()


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
        key = inv.file_path.split("r2.dev/")[-1]
        try:
            s3.delete_object(Bucket=R2_BUCKET, Key=key)
        except:
            pass

    await db.commit()
    return True


async def list_inventory(db, owner_id):
    await sync_products_to_inventory(db, owner_id)

    res = await db.execute(
        select(models.SalesInventoryItem)
        .where(models.SalesInventoryItem.owner_id == owner_id)
        .order_by(models.SalesInventoryItem.id.desc())
    )
    return res.scalars().all()


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
            # reduce but don’t go below 0
            inv.quantity = max((inv.quantity or 0) - qty, 0)

    await db.commit()


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

    # safety: never drop below zero
    inv.quantity = max((inv.quantity or 0) + delta, 0)

    await db.commit()
    return inv


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


async def get_invoice_with_items(db, owner_id, invoice_id):
    res = await db.execute(
        select(models.SalesInvoice)
        .options(
            selectinload(models.SalesInvoice.line_items),
            selectinload(models.SalesInvoice.line_items).selectinload(
                models.SalesInvoiceLineItem.product
            ),
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

    # Get max invoice number for today
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
        last_num = int(last.split("-")[-1])
    except:
        last_num = 0

    next_num = last_num + 1
    return f"{prefix}{next_num:03d}"
