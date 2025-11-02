# doc_prompts.py

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
 "vat_license_holder_name": string | null,
 "vat_license_issuing_authority": string | null,
 "vat_license_number": string | null,
 "vat_date_of_issue": string | null,
 "vat_version_number": string | null
}

Rules:
- Output ONLY JSON, no markdown.
- Never invent values, use null if not present.
- Dates must be dd/mm/yyyy or yyyy-mm-dd if readable.
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
