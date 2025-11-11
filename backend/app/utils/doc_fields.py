VAT_FIELDS = [
    "vat_certificate_title",
    "vat_issuing_authority",
    "vat_tax_registration_number",
    "vat_legal_name_arabic",
    "vat_legal_name_english",
    "vat_registered_address",
    "vat_contact_number",
    "vat_effective_registration_date",
    "vat_first_vat_return_period",
    "vat_vat_return_due_date",
    "vat_tax_periods",
    "vat_license_holder_name",
    "vat_license_issuing_authority",
    "vat_license_number",
    "vat_date_of_issue",
    "vat_version_number",
    "vat_batch_one",
    "vat_batch_two",
    "vat_batch_three",
    "vat_batch_four",
]

CT_FIELDS = [
    "ct_certificate_title",
    "ct_issuing_authority",
    "ct_trn",
    "ct_legal_name_ar",
    "ct_legal_name_en",
    "ct_registered_address",
    "ct_contact_number",
    "ct_effective_registration_date",
    "ct_tax_period",
    # First Corporate Tax Period
    "ct_first_period_start_date",
    "ct_first_period_end_date",
    "ct_first_return_due_date",
    # License info
    "ct_license_holder_name",
    "ct_license_authority",
    "ct_license_number",
    "ct_license_issue_date",
    "ct_version_number",
]

TL_FIELDS = [
    "tl_license_number",
    "tl_membership_number",
    "tl_registration_number",
    "tl_business_name_ar",
    "tl_business_name_en",
    "tl_legal_status",
    "tl_activities",
    "tl_issue_date",
    "tl_expiry_date",
    "tl_membership_since",
]

PASSPORT_FIELDS = [
    "passport_number",
    "passport_name",
    "passport_date_of_birth",
    "passport_issue_date",
    "passport_expiry_date",
]

EMIRATES_ID_FIELDS = [
    "emirates_id_number",
    "emirates_id_name",
    "emirates_id_date_of_birth",
    "emirates_id_issue_date",
    "emirates_id_expiry_date",
]


DOC_TYPE_MAP = {
    "vat_certificate": VAT_FIELDS,
    "ct_certificate": CT_FIELDS,
    "trade_license": TL_FIELDS,
    "passport": PASSPORT_FIELDS,
    "emirates_id": EMIRATES_ID_FIELDS,
}
