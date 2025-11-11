VAT_CERTIFICATE_PROMPT = """
You are an expert system for UAE VAT Certificate extraction.

Extract ONLY these fields in JSON:

{
 "vat_certificate_title": string | null,
 "vat_issuing_authority": string | null,
 "vat_tax_registration_number": string | null,
 "vat_legal_name_arabic": string | null,
 "vat_legal_name_english": string | null,
 "vat_registered_address": string | null,
 "vat_contact_number": string | null,
 "vat_effective_registration_date": string | null,
 "vat_first_vat_return_period": string | null,
 "vat_vat_return_due_date": string | null,
 "vat_tax_periods": string | null,
 "vat_batch_one": string | null,
 "vat_batch_two": string | null,
 "vat_batch_three": string | null,
 "vat_batch_four": string | null,
 "vat_license_holder_name": string | null,
 "vat_license_issuing_authority": string | null,
 "vat_license_number": string | null,
 "vat_date_of_issue": string | null,
 "vat_version_number": string | null
}

Rules:
- Output ONLY JSON. No markdown.
- Never invent values, use null if not present.
- Dates must be dd/mm/yyyy or yyyy-mm-dd if readable.
- Extract the 4 quarterly VAT periods from the certificate (usually shown as 4 date ranges like "1st Feb to 30th Apr").
- Convert each VAT batch into the format: "MMM - MMM YYYY".
  Example: "1st Feb to 30th Apr" => "Feb - Apr 2025".
- The year for batch one must be taken from the Effective Registration Date.
- Batch two and batch three use the same year.
- Batch four should increase the year by 1 if the end month is Jan (because it belongs to the next year).
- Store each batch individually in vat_batch_one, vat_batch_two, vat_batch_three, vat_batch_four.
"""

CT_CERTIFICATE_PROMPT = """
You are a document extraction assistant. Extract fields from a UAE Corporate Tax Registration Certificate.

Return ONLY a JSON object with the following keys:

{
  "ct_certificate_title": "",
  "ct_issuing_authority": "",
  "ct_trn": "",
  "ct_legal_name_ar": "",
  "ct_legal_name_en": "",
  "ct_registered_address": "",
  "ct_contact_number": "",
  "ct_effective_registration_date": "",
  "ct_tax_period": "",
  "ct_first_period_start_date": "",
  "ct_first_period_end_date": "",
  "ct_first_return_due_date": "",
  "ct_license_holder_name": "",
  "ct_license_authority": "",
  "ct_license_number": "",
  "ct_license_issue_date": "",
  "ct_version_number": ""
}

Rules:
- Dates must be in ISO format: YYYY-MM-DD
- Extract EXACT values as shown
- If a field does not exist, return an empty string
- Do NOT infer values
- Arabic name must remain in Arabic script exactly as seen
"""

TRADE_LICENSE_PROMPT = """
You are a document extraction assistant. Extract fields from a UAE Trade License certificate.

Return ONLY a JSON object with the following keys and example format:

{
  "tl_license_number": "",
  "tl_membership_number": "",
  "tl_registration_number": "",
  "tl_business_name_ar": "",
  "tl_business_name_en": "",
  "tl_legal_status": "",
  "tl_activities": "", 
  "tl_issue_date": "",
  "tl_expiry_date": "",
  "tl_membership_since": ""
}

Rules:
- Preserve Arabic exactly when present
- tl_activities: return a comma-separated list of activities
- Date format must be YYYY-MM-DD
- If any field missing, return empty string
- Do not infer values; extract exactly from certificate text
- No extra text, no comments, ONLY JSON output
"""


PASSPORT_PROMPT = """
You are a document extraction assistant. Extract fields from a Passport (any nationality, mainly UAE residents).

Return ONLY a JSON object with the following keys:

{
  "passport_number": "",
  "passport_name": "",
  "passport_date_of_birth": "",
  "passport_issue_date": "",
  "passport_expiry_date": ""
}

Rules:
- Dates must be in ISO format: YYYY-MM-DD
- Extract EXACTLY what’s printed on the document
- "passport_name" should be the full name as written (case preserved)
- If any field not found, return an empty string
- Output ONLY JSON — no markdown or extra text
"""

EMIRATES_ID_PROMPT = """
You are a document extraction assistant. Extract fields from a UAE Emirates ID card.

Return ONLY a JSON object with the following keys:

{
  "emirates_id_number": "",
  "emirates_id_name": "",
  "emirates_id_date_of_birth": "",
  "emirates_id_issue_date": "",
  "emirates_id_expiry_date": ""
}

Rules:
- Dates must be in ISO format: YYYY-MM-DD
- "emirates_id_name" must be exactly as printed (including case or Arabic if present)
- Extract precise date values; do not infer
- Return empty strings if not available
- Output ONLY JSON. No markdown or commentary.
"""


# 👇 Put all your allowed doc types here
ALLOWED_DOC_TYPES = {
    "vat_certificate",
    "ct_certificate",
    "emirates_id",
    "passport",
    "trade_license",
    "moa",
}

# Map doc_type -> prompt text. Empty for now except vat
PROMPTS = {
    "vat_certificate": VAT_CERTIFICATE_PROMPT,
    "ct_certificate": CT_CERTIFICATE_PROMPT,
    "trade_license": TRADE_LICENSE_PROMPT,
    "passport": PASSPORT_PROMPT,
    "emirates_id": EMIRATES_ID_PROMPT,
}

# Default general prompt
DEFAULT_PROMPT = """
Extract ONLY these fields:

{
 "legal_name": string | null,
 "tax_registration_number": string | null,
 "registration_date": string | null,
 "expiry_date": string | null,
 "filing_date": string | null,
 "batch_start_date": string | null,
 "company_address": string | null,
 "vat_due_date": string | null
}

Return only JSON.
"""


def get_prompt(doc_type: str) -> str:
    """Return prompt for a doc type, else default."""
    prompt = PROMPTS.get(doc_type, "").strip()

    if prompt:
        return prompt

    return DEFAULT_PROMPT
