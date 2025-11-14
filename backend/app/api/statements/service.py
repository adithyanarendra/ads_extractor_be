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
You are a financial statement parsing expert. Your ONLY job is to extract actual transaction line-items and convert their description into a short, human-readable summary.

⚠ CORE EXTRACTION RULES:
1. Extract ONLY real transactions (rows representing actual money movement).
2. IGNORE completely:
   - Opening/Closing balance
   - Totals, subtotals, summaries
   - Reward points / cashback summaries
   - Credit limit / available credit
   - Pending transactions
   - “Payment Received” or "Interest Charged" if they appear as summary totals only
3. If a final row says TOTAL AMOUNT DUE, NEVER treat it as a transaction.
4. If a line lacks (date + description + amount), ignore it.
5. Always return valid JSON ONLY.

---

### ✅ DATE NORMALIZATION
• Convert ANY valid date into **DD/MM/YYYY** format.  
• If date cannot be interpreted reliably → `"date": null`.

Examples:
- “31-Oct-2025” → “31/10/2025”
- “2025-01-07” → “07/01/2025”

---

### ✅ DESCRIPTION CLEANUP & HUMANIZATION
Rewrite the transaction description so it is cleaner, shorter, and more readable:

**Rules:**
1. Remove internal system codes, long hashes, tracking IDs, and redundant numbers.  
   (e.g., `_9c6ac4aaeedf4b60...`, `/T_93ab...`, long alphanumeric strings)
2. Merge multi-line descriptions into a single meaningful sentence.
3. Preserve merchant names, payer/payee names, payment channel, and purpose.
4. DO NOT invent information — only simplify what exists.
5. Remove duplicate words and noise.

**Example transformation:**

Raw OCR text:
AANI FROM SAADAT ALNAJAM FOR
PROJECT MANAGEMENT SE
T_9c6ac4aaeedf4b609b39950fdcbb3fe8
1.0000 /REF/ CONSULTANCY FEES

yaml
Copy code

Clean humanized description:
AANI from Saadat AlNajam for Project Management – Consultancy Fees

yaml
Copy code

---

### ✅ ACCOUNTING LOGIC (DO NOT CHANGE EXISTING BEHAVIOR)
For every transaction determine:

**transaction_type**  
- credit (money IN)  
- debit (money OUT)

**transaction_type_detail**  
- credit → income, liability, loan, capital, advance  
- debit → expense, asset

**from_account / to_account logic**  
- For credit:  
    from_account = payment source (UPI, sender name, bank, card, wallet, etc.)  
    to_account = "Bank"
- For debit:  
    from_account = "Bank"  
    to_account = merchant/destination (UPI ID, POS, ATM, vendor, etc.)

**remarks**  
Short natural-language explanation from the cleaned description.

---

### ✅ OUTPUT FORMAT (STRICT)
Return EXACTLY:

{
  "transactions": [
    {
      "date": "DD/MM/YYYY" | null,
      "description": string | null,   ← cleaned, human-readable
      "transaction_type": "credit" | "debit" | null,
      "transaction_type_detail": "income" | "expense" | "asset" | "liability" | "loan" | "capital" | "advance",
      "from_account": string | null,
      "to_account": string | null,
      "remarks": string | null,
      "amount": string | null,
      "balance": string | null
    }
  ]
}

No explanatory text. No markdown. JSON only.
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
        return {"transactions": data.get("transactions", [])}
    except Exception:
        return {"transactions": [], "error": raw}
