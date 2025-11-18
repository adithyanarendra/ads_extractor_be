import os
import base64
import mimetypes
from pdf2image import convert_from_bytes
from io import BytesIO
from dotenv import load_dotenv
from openai import OpenAI
import json
import re

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def convert_pdf_to_images(file_bytes: bytes):
    images = convert_from_bytes(file_bytes, fmt="png", dpi=200)
    output = []
    for img in images:
        buf = BytesIO()
        img.save(buf, format="PNG")
        output.append(("image/png", base64.b64encode(buf.getvalue()).decode()))
    return output


STATEMENT_PROMPT = """
You are a UAE financial statement parsing expert. Your ONLY job is:
1. Extract actual transaction rows.
2. Extract the primary *account number* associated with the statement.
3. Extract transaction IDs such as UTR, RRN, Auth Code, Ref No, Cheque No, or any UAE bank transaction reference.

⚠ CORE EXTRACTION RULES:
1. Extract ONLY real transactions (rows showing money movement).
2. IGNORE completely:
   - Opening/Closing balance
   - Totals / subtotals / summary rows
   - Reward points, cashback summaries
   - Credit limit / available credit
   - Pending transactions
   - “Payment Received” or “Interest Charged” if summary-only
3. If a final row says TOTAL AMOUNT DUE → never treat it as a transaction.
4. Ignore any line missing (date + description + amount).
5. Always return valid JSON only.

---

### ✅ UAE ACCOUNT NUMBER EXTRACTION RULES (VERY STRICT)
Your goal is to extract the **primary bank account number** for this statement.

Extraction Priority (in strict order):

1️⃣ **Bank Account Number (Preferred)**  
   - 8–14 consecutive digits  
   - Usually appears near:  
     • “Account No”  
     • “A/C No”  
     • “Account Number”  
     • “Account #”  
     • Top header of statement pages  

2️⃣ **Credit Card Number (masked or last 4 digits)**  
   Valid formats:  
   - XXXX-XXXX-XXXX-1234  
   - **** **** **** 5678  
   - ************4321  

3️⃣ **IBAN (ONLY if no account number exists anywhere)**  
   - Must start with AE + 21 digits  
   - Example: AE070031234567890123456  

⚠ IMPORTANT  
- DO NOT return the IBAN if an account number is present anywhere in the document.  
- DO NOT extract Customer ID, CIF, mobile numbers, or payment reference numbers as account numbers.  

Return:  
- `"account_number": string | null`  
- `"provider": bank name if identifiable (Emirates NBD, ADCB, FAB, Mashreq, RAKBANK, HSBC UAE, etc.)`  

---

### ✅ UAE TRANSACTION ID EXTRACTION (EXTREMELY PRECISE)
For each transaction, extract ANY transaction reference visible in the same row or in the "Transaction ID / Cheque Number" column.

You MUST capture:
- UTR numbers  
- RRN  
- Auth/Approval Codes  
- Ref No or Reference Number  
- Transaction ID (TXN- or numeric)  
- Cheque Number  
- Any code appearing in a column labelled:
  • “Transaction ID”  
  • “Txn ID”  
  • “Reference No”  
  • “Ref No”  
  • “Cheque No”  
  • “Transaction ID / Cheque Number”  

Valid examples:
- UTR: 1234567890  
- RRN: 482918374982  
- Auth Code: 939402  
- Ref No: A12939492  
- TXN-129394  
- CHQ123456  
- Cheque No: 002918  
- 12–18 digit UAE internal reference codes  

Rules:
1. If multiple IDs appear → choose the most explicit transaction reference.  
2. If nothing looks like a transaction ID → return null.  
3. Never invent IDs.  

Return value (per transaction):
- `"transaction_id": string | null`

---

### ✅ DATE NORMALIZATION
Convert all dates to **DD/MM/YYYY** format.

Examples:
- “31-Oct-2024” → “31/10/2024”
- “2024-01-07” → “07/01/2024”

---

### ✅ DESCRIPTION CLEANUP
Rewrite descriptions so they are clean and readable:

Rules:
1. Remove hashes, long codes, noise (unless they are transaction IDs).
2. Merge multi-line descriptions into one line.
3. Preserve merchant/payer name, channel, purpose.
4. Never invent missing information.

---

### ACCOUNTING LOGIC (UPDATED — VERY STRICT)
transaction_type:
- credit → money IN  
- debit → money OUT  

transaction_type_detail:
- credit → income / liability / loan / capital / advance  
- debit → expense / asset  

from_account / to_account (VERY STRICT):
- For ALL credits (money IN): 
    to_account MUST be exactly "Bank".
    from_account = the payer/source (clean name).

- For ALL debits (money OUT):
    from_account MUST be exactly "Bank".
    to_account = merchant/recipient (clean name).

⚠ NEVER return bank names (Emirates NBD, ADCB, HDFC, RAKBANK, etc.) in from_account or to_account.
⚠ Use the literal string "Bank" only.

---

### ✅ STRICT OUTPUT FORMAT
Return exactly:

{
  "account_number": string | null,
  "provider": string | null,
  "transactions": [
    {
      "date": "DD/MM/YYYY" | null,
      "description": string | null,
      "transaction_type": "credit" | "debit" | null,
      "transaction_type_detail": "income" | "expense" | "asset" | "liability" | "loan" | "capital" | "advance",
      "from_account": string | null,
      "to_account": string | null,
      "remarks": string | null,
      "amount": string | null,
      "balance": string | null,
      "transaction_id": string | null
    }
  ]
}

No markdown. No explanations. JSON only.

"""


async def parse_statement(file_bytes: bytes, file_ext: str):
    mime, _ = mimetypes.guess_type("file" + file_ext)

    if mime == "application/pdf":
        images = convert_pdf_to_images(file_bytes)
    else:
        images = [(mime, base64.b64encode(file_bytes).decode())]

    gpt_input = [{"type": "input_text", "text": STATEMENT_PROMPT}]
    for mime, b64 in images[:3]:
        gpt_input.append(
            {
                "type": "input_image",
                "image_url": f"data:{mime};base64,{b64}",
            }
        )

    response = client.responses.create(
        model="gpt-4.1",
        input=[{"role": "user", "content": gpt_input}],
    )

    raw = response.output_text.strip()

    if "```" in raw:
        m = re.search(r"```(?:json)?(.*?)```", raw, re.DOTALL)
        if m:
            raw = m.group(1).strip()

    try:
        data = json.loads(raw)
        return {
            "account_number": data.get("account_number"),
            "provider": data.get("provider"),
            "transactions": data.get("transactions", []),
            "raw": data,
        }
    except Exception:
        return {"transactions": [], "error": raw}
