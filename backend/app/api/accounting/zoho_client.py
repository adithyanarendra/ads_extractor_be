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
    
    def get_chart_of_accounts(self) -> Dict:
        """Fetch all accounts from Zoho"""
        try:
            url = f"{self.base_url}/chartofaccounts"
            params = {"organization_id": self.org_id}
            response = requests.get(url, headers=self.headers, params=params)
            return response.json()
        except Exception as e:
            return {"error": str(e)}
    
    def get_or_create_customer(self, customer_name: str) -> Optional[str]:
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
            
            if "contacts" in data and len(data["contacts"]) > 0:
                return data["contacts"][0]["contact_id"]
            
            create_data = {
                "contact_name": customer_name,
                "contact_type": "customer",
                "organization_id": self.org_id
            }
            response = requests.post(url, headers=self.headers, json=create_data)
            result = response.json()
            
            if "contact" in result:
                return result["contact"]["contact_id"]
            
            return None
        except Exception as e:
            print(f"Error with customer: {str(e)}")
            return None
    
    def get_or_create_vendor(self, vendor_name: str) -> Optional[str]:
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
                return data["contacts"][0]["contact_id"]
            
            create_data = {
                "contact_name": vendor_name,
                "contact_type": "vendor",
                "organization_id": self.org_id
            }
            response = requests.post(url, headers=self.headers, json=create_data)
            result = response.json()
            
            if "contact" in result:
                return result["contact"]["contact_id"]
            
            return None
        except Exception as e:
            print(f"Error with vendor: {str(e)}")
            return None
    
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
                "line_items": [
                    {
                        "account_id": bill_data["account_id"],
                        "description": bill_data.get("description", ""),
                        "rate": float(bill_data.get("amount", 0)),
                        "quantity": 1,
                    }
                ],
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
                "line_items": [
                    {
                        "account_id": invoice_data.get("account_id"),
                        "description": invoice_data.get("description", ""),
                        "rate": float(invoice_data.get("amount", 0)),
                        "quantity": 1,
                    }
                ],
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
        
        if not account_id:
            return {"success": 0, "failed": len(invoices), "error": "Missing account_id"}

        summary = {"success": 0, "failed": 0, "errors": [], "details": []}

        for invoice in invoices:
            invoice_id = invoice.get("id")

            if invoice_type == "sales":
                customer_name = invoice.get("customer_name") or invoice.get("vendor_name") or "Unknown Customer"
                customer_id = self.get_or_create_customer(customer_name)
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
                    "account_id": account_id,
                }
                result = self.create_sales_invoice(invoice_payload)
            else:
                vendor_name = invoice.get("vendor_name") or "Unknown Vendor"
                vendor_id = self.get_or_create_vendor(vendor_name)
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
                    "account_id": account_id,
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
