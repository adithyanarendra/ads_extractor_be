import requests
import os
from typing import Dict, List, Optional
from sqlalchemy import update
from app.api.invoices.models import Invoice
from sqlalchemy.ext.asyncio import AsyncSession

class ZohoClient:
    """Handle all Zoho Books API calls"""
    
    def __init__(self, access_token: str, org_id: str):
        self.access_token = access_token
        self.org_id = org_id
        self.base_url = os.getenv("ZOHO_BASE_URL", "https://www.zohoapis.com/books/v3")
        self.headers = {
            "Authorization": f"Zoho-oauthtoken {access_token}",
            "Content-Type": "application/json"
        }
        self._standard_tax_id = None
    
    def get_chart_of_accounts(self) -> Dict:
        """Fetch all accounts from Zoho"""
        try:
            url = f"{self.base_url}/chartofaccounts"
            params = {"organization_id": self.org_id}
            response = requests.get(url, headers=self.headers, params=params)
            return response.json()
        except Exception as e:
            return {"error": str(e)}
        
    def get_bills(self, date_start: str, date_end: str) -> Dict:
        """Fetch bills from Zoho Books"""
        try:
            url = f"{self.base_url}/bills"
            params = {
                "organization_id": self.org_id,
                "date_start": date_start,
                "date_end": date_end,
            }
            response = requests.get(url, headers=self.headers, params=params)
            return response.json()
        except Exception as e:
            return {"error": str(e)}

    def _get_standard_tax_id(self) -> Optional[str]:
        if self._standard_tax_id:
            return self._standard_tax_id
        try:
            url = f"{self.base_url}/settings/taxes"
            params = {"organization_id": self.org_id}
            response = requests.get(url, headers=self.headers, params=params)
            data = response.json()
            taxes = data.get("taxes") or []
            for tax in taxes:
                percentage = tax.get("tax_percentage")
                name = (tax.get("tax_name") or "").lower()
                if percentage == 5 or percentage == 5.0 or "standard" in name:
                    self._standard_tax_id = tax.get("tax_id")
                    return self._standard_tax_id
        except Exception as e:
            print(f"Error fetching Zoho taxes: {str(e)}")
        return None

    def _sanitize_trn(self, trn: str | None) -> Optional[str]:
        if not trn:
            return None
        digits = "".join(ch for ch in str(trn) if ch.isdigit())
        if len(digits) == 15:
            return digits
        return None

    def _update_contact_tax(self, contact_id: str, trn: str) -> None:
        trn_clean = self._sanitize_trn(trn)
        if not trn_clean:
            print(f"Skipping contact tax update due to invalid TRN: {trn}")
            return
        url = f"{self.base_url}/contacts/{contact_id}"
        params = {"organization_id": self.org_id}
        payload = {
            "tax_treatment": "vat_registered",
            "tax_reg_no": trn_clean,
        }
        try:
            response = requests.put(
                url, headers=self.headers, params=params, json=payload
            )
            result = response.json()
            if result.get("code") == 0:
                return
            msg = str(result.get("message", "")).lower()
            if "tax_treatment" in msg or "tax_reg_no" in msg:
                fallback = {"gst_treatment": "business_gst", "gst_no": trn_clean}
                requests.put(
                    url, headers=self.headers, params=params, json=fallback
                )
        except Exception as e:
            print(f"Error updating contact tax: {str(e)}")

    def get_or_create_customer(self, customer_name: str, trn: str | None = None) -> Optional[str]:
        """Get customer or create if doesn't exist (for Sales invoices)"""
        try:
            url = f"{self.base_url}/contacts"
            params = {
                "organization_id": self.org_id,
                "contact_name": customer_name,
                "contact_type": "customer"
            }
            response = requests.get(url, headers=self.headers, params=params)
            data = response.json()
            if data.get("code") not in (0, None):
                print(f"Zoho vendor lookup error: {data}")
            
            if "contacts" in data and len(data["contacts"]) > 0:
                contact_id = data["contacts"][0]["contact_id"]
                if trn:
                    self._update_contact_tax(contact_id, trn)
                return contact_id
            
            create_data = {
                "contact_name": customer_name,
                "contact_type": "customer",
                "organization_id": self.org_id
            }
            trn_clean = self._sanitize_trn(trn)
            if trn_clean:
                create_data["tax_treatment"] = "vat_registered"
                create_data["tax_reg_no"] = trn_clean
            response = requests.post(url, headers=self.headers, json=create_data)
            result = response.json()
            if result.get("code") not in (0, None):
                print(f"Zoho vendor create error: {result}")

            if result.get("code") != 0:
                msg = str(result.get("message", "")).lower()
                if "tax_treatment" in msg or "tax_reg_no" in msg:
                    create_data.pop("tax_treatment", None)
                    create_data.pop("tax_reg_no", None)
                    if trn_clean:
                        create_data["gst_treatment"] = "business_gst"
                        create_data["gst_no"] = trn_clean
                    response = requests.post(url, headers=self.headers, json=create_data)
                    result = response.json()
                    if result.get("code") not in (0, None):
                        print(f"Zoho vendor create retry error: {result}")
            
            if "contact" in result:
                return result["contact"]["contact_id"]
            
            return None
        except Exception as e:
            print(f"Error with customer: {str(e)}")
            return None
    
    def get_or_create_vendor(self, vendor_name: str, trn: str | None = None) -> Optional[str]:
        """Get vendor or create if doesn't exist (for Purchase bills)"""
        try:
            url = f"{self.base_url}/contacts"
            params = {
                "organization_id": self.org_id,
                "contact_name": vendor_name,
                "contact_type": "vendor"
            }
            response = requests.get(url, headers=self.headers, params=params)
            data = response.json()
            
            if "contacts" in data and len(data["contacts"]) > 0:
                contact_id = data["contacts"][0]["contact_id"]
                if trn:
                    self._update_contact_tax(contact_id, trn)
                return contact_id
            
            create_data = {
                "contact_name": vendor_name,
                "contact_type": "vendor",
                "organization_id": self.org_id
            }
            trn_clean = self._sanitize_trn(trn)
            if trn_clean:
                create_data["tax_treatment"] = "vat_registered"
                create_data["tax_reg_no"] = trn_clean
            response = requests.post(url, headers=self.headers, json=create_data)
            result = response.json()

            if result.get("code") != 0:
                msg = str(result.get("message", "")).lower()
                if "tax_treatment" in msg or "tax_reg_no" in msg:
                    create_data.pop("tax_treatment", None)
                    create_data.pop("tax_reg_no", None)
                    if trn_clean:
                        create_data["gst_treatment"] = "business_gst"
                        create_data["gst_no"] = trn_clean
                    response = requests.post(url, headers=self.headers, json=create_data)
                    result = response.json()
            
            if "contact" in result:
                return result["contact"]["contact_id"]
            
            return None
        except Exception as e:
            print(f"Error with vendor: {str(e)}")
            return None

    def _parse_percent(self, value) -> Optional[float]:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value).strip().replace("%", "")
        try:
            return float(text)
        except ValueError:
            return None

    def _parse_amount(self, value) -> Optional[float]:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value).strip().replace(",", "")
        try:
            return float(text)
        except ValueError:
            return None

    def _tax_percentage_for_item(self, trn: Optional[str], item: Dict) -> Optional[float]:
        if not trn:
            return None
        tax_rate = item.get("tax_rate") or item.get("tax_percentage")
        percent = self._parse_percent(tax_rate)
        if percent is not None:
            return percent
        tax_amount = item.get("tax") or item.get("tax_amount")
        unit_price = item.get("unit_price") or item.get("rate")
        quantity = item.get("quantity") or 1
        if unit_price:
            base_amount = (self._parse_amount(unit_price) or 0) * float(quantity)
        else:
            base_amount = item.get("amount") or item.get("before_tax_amount")
        try:
            tax_val = self._parse_amount(tax_amount) or 0
            base_val = self._parse_amount(base_amount) or 0
            if base_val > 0 and tax_val > 0:
                return round((tax_val / base_val) * 100, 2)
        except (TypeError, ValueError):
            return None
        return 5.0

    def _build_line_items(self, data: Dict) -> List[Dict]:
        raw_items = data.get("line_items") or []
        trn = data.get("trn_vat_number")
        account_id = data.get("account_id")
        invoice_tax_amount = self._parse_amount(data.get("tax_amount")) or 0
        has_tax = invoice_tax_amount > 0
        tax_id = self._get_standard_tax_id() if (trn and has_tax) else None
        if raw_items:
            items = []
            for item in raw_items:
                unit_price = item.get("unit_price") or item.get("rate")
                quantity = item.get("quantity") or 1
                line_item = {
                    "account_id": account_id,
                    "description": item.get("description") or data.get("description", ""),
                    "rate": self._parse_amount(unit_price) or 0,
                    "quantity": quantity,
                }
                if has_tax:
                    if tax_id:
                        line_item["tax_id"] = tax_id
                    else:
                        tax_percentage = self._tax_percentage_for_item(trn, item)
                        if tax_percentage is not None and tax_percentage > 0:
                            line_item["tax_percentage"] = tax_percentage
                items.append(line_item)
            return items

        line_item = {
            "account_id": account_id,
            "description": data.get("description", ""),
            "rate": self._parse_amount(data.get("before_tax_amount", 0)) or 0,
            "quantity": 1,
        }
        if has_tax:
            if tax_id:
                line_item["tax_id"] = tax_id
            else:
                tax_percentage = self._tax_percentage_for_item(trn, data)
                if tax_percentage is not None and tax_percentage > 0:
                    line_item["tax_percentage"] = tax_percentage
        return [line_item]
    
    def create_bill(self, bill_data: Dict) -> Dict:
        """Create a Purchase Bill in Zoho Books (for expense invoices)"""
        try:
            url = f"{self.base_url}/bills"
            
            bill_date = bill_data.get("bill_date", "")
            if bill_date and len(bill_date) == 10 and bill_date[2] == '-':
                parts = bill_date.split('-')
                if len(parts) == 3:
                    d, m, y = parts
                    bill_date = f"{y}-{m}-{d}"
            
            payload = {
                "vendor_id": bill_data["vendor_id"],
                "bill_number": bill_data.get("bill_number", ""),
                "date": bill_date,
                "line_items": self._build_line_items(bill_data),
            }
            
            params = {"organization_id": self.org_id}
            
            print(f"Creating bill with payload: {payload}")
            
            response = requests.post(url, headers=self.headers, params=params, json=payload)
            result = response.json()
            
            print(f"Zoho create_bill response: {result}")
            
            return result
            
        except Exception as e:
            print(f"Error creating bill: {str(e)}")
            return {"error": str(e)}

    def create_sales_invoice(self, invoice_data: Dict) -> Dict:
        """Create a Sales Invoice in Zoho Books (for sales invoices)"""
        try:
            url = f"{self.base_url}/invoices"
            
            invoice_date = invoice_data.get("invoice_date", "")
            if invoice_date and len(invoice_date) == 10 and invoice_date[2] == '-':
                parts = invoice_date.split('-')
                if len(parts) == 3:
                    d, m, y = parts
                    invoice_date = f"{y}-{m}-{d}"
            
            payload = {
                "customer_id": invoice_data["customer_id"],
                "date": invoice_date,
                "line_items": self._build_line_items(invoice_data),
            }
            
            params = {"organization_id": self.org_id}
            
            print(f"Creating sales invoice with payload: {payload}")
            
            response = requests.post(url, headers=self.headers, params=params, json=payload)
            result = response.json()
            
            print(f"Zoho create_sales_invoice response: {result}")
            
            return result
            
        except Exception as e:
            print(f"Error creating sales invoice: {str(e)}")
            return {"error": str(e)}

    async def update_invoice_by_id(self, db: AsyncSession, invoice_id: int):
        stmt = (
            update(Invoice)
            .where(Invoice.id == invoice_id)
            .values(accounting_software="zb")
            .execution_options(synchronize_session=False)
        )

        await db.execute(stmt)
        await db.commit()

    async def push_multiple_invoices(self, payload: Dict, db: AsyncSession) -> Dict:
        """Push multiple invoices to Zoho (expense bills or sales invoices)"""
        invoices = payload.get("invoices", [])
        account_id = payload.get("account_id")
        invoice_type = payload.get("invoice_type", "expense")

        summary = {"success": 0, "failed": 0, "errors": [], "details": []}

        for invoice in invoices:
            invoice_id = invoice.get("id")
            invoice_account_id = invoice.get("account_id") or account_id

            if not invoice_account_id:
                summary["failed"] += 1
                summary["errors"].append(
                    f"Missing Chart of Account for invoice {invoice_id}"
                )
                continue

            if invoice_type == "sales":
                customer_name = invoice.get("customer_name") or invoice.get("vendor_name") or "Unknown Customer"
                customer_id = self.get_or_create_customer(
                    customer_name, invoice.get("trn_vat_number")
                )
                if not customer_id:
                    summary["failed"] += 1
                    summary["errors"].append(f"Customer lookup failed for {customer_name}")
                    continue

                invoice_payload = {
                    "customer_id": customer_id,
                    "invoice_number": invoice.get("invoice_number"),
                    "invoice_date": invoice.get("bill_date") or invoice.get("invoice_date"),
                    "description": invoice.get("description"),
                    "amount": invoice.get("amount"),
                    "account_id": invoice_account_id,
                    "trn_vat_number": invoice.get("trn_vat_number"),
                    "tax_amount": invoice.get("tax_amount"),
                    "before_tax_amount": invoice.get("before_tax_amount"),
                    "line_items": invoice.get("line_items"),
                }
                result = self.create_sales_invoice(invoice_payload)
            else:
                vendor_name = invoice.get("vendor_name") or "Unknown Vendor"
                vendor_id = self.get_or_create_vendor(
                    vendor_name, invoice.get("trn_vat_number")
                )
                if not vendor_id:
                    summary["failed"] += 1
                    summary["errors"].append(f"Vendor lookup failed for {vendor_name}")
                    continue

                bill_payload = {
                    "vendor_id": vendor_id,
                    "bill_number": invoice.get("invoice_number"),
                    "bill_date": invoice.get("bill_date"),
                    "description": invoice.get("description"),
                    "amount": invoice.get("amount"),
                    "account_id": invoice_account_id,
                    "trn_vat_number": invoice.get("trn_vat_number"),
                    "tax_amount": invoice.get("tax_amount"),
                    "before_tax_amount": invoice.get("before_tax_amount"),
                    "line_items": invoice.get("line_items"),
                }
                result = self.create_bill(bill_payload)

            # Detect duplicate errors from Zoho (e.g., bill already exists)
            is_duplicate = False
            if isinstance(result, dict):
                msg = (result.get("message") or "").lower()
                if result.get("code") == 13011 or "already been created" in msg or "already exists" in msg:
                    is_duplicate = True

            if isinstance(result, dict) and result.get("code") == 0:
                summary["success"] += 1
                summary["details"].append(
                    {"invoice_id": invoice_id, "status": "success"}
                )
                if invoice_id is not None:
                    await self.update_invoice_by_id(db, invoice_id)
            elif is_duplicate:
                summary["success"] += 1
                summary["details"].append(
                    {
                        "invoice_id": invoice_id,
                        "status": "duplicate",
                        "error": result.get("message"),
                    }
                )
                if invoice_id is not None:
                    await self.update_invoice_by_id(db, invoice_id)
            else:
                summary["failed"] += 1
                msg = result.get("message") if isinstance(result, dict) else str(result)
                summary["errors"].append(msg)
                summary["details"].append(
                    {"invoice_id": invoice_id, "status": "failed", "error": msg}
                )

        return summary

    def get_invoices(self, date_start: str, date_end: str) -> Dict:
        """Fetch sales invoices from Zoho Books"""
        try:
            url = f"{self.base_url}/invoices"
            params = {
                "organization_id": self.org_id,
                "date_start": date_start,
                "date_end": date_end,
            }
            response = requests.get(url, headers=self.headers, params=params)
            return response.json()
        except Exception as e:
            return {"error": str(e)}
