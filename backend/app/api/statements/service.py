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
You are a financial statement parsing expert. Your ONLY job is to extract actual transaction line-items.

⚠ STRICT RULES:
1. Extract ONLY real transactions (rows that represent money movement).
2. IGNORE the following completely:
   - Opening balance
   - Closing balance
   - Total / Subtotal / Summary rows
   - Reward points, cashbacks summary, or points balances
   - Pending transactions
   - Available credit / credit limit
   - Statement totals (e.g., Total Due, Minimum Due)
   - "Payment Received", “Interest Charged”, if marked as summary totals instead of line transactions
   - Any line that contains ONLY totals, balances, or summary values

3. If a credit card statement has a final line with TOTAL AMOUNT DUE, DO NOT treat it as a transaction.

4. If a line does not clearly contain a financial transaction (date + description + amount), IGNORE it.

5. Return dates exactly as found, or convert to DD-MM-YYYY format when possible. Use null when unclear.

6. Always produce valid JSON only.

OUTPUT FORMAT (NO extra text):
{
  "transactions": [
    {
      "date": "DD-MM-YYYY" | null,
      "description": string | null,
      "transaction_type": "credit" | "debit" | null,
      "amount": string | null,
      "balance": string | null
    }
  ]
}

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
