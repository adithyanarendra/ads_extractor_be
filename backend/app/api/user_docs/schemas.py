from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class BaseDocSchema(BaseModel):
    file_name: str
    file_url: str
    expiry_date: Optional[datetime]
    filing_date: Optional[datetime]
    batch_start_date: Optional[datetime]
    company_address: Optional[str]
    uploaded_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class VATCertificateSchema(BaseDocSchema):
    vat_certificate_title: Optional[str]
    vat_issuing_authority: Optional[str]
    vat_tax_registration_number: Optional[str]
    vat_legal_name_arabic: Optional[str]
    vat_legal_name_english: Optional[str]
    vat_registered_address: Optional[str]
    vat_contact_number: Optional[str]
    vat_effective_registration_date: Optional[datetime]
    vat_first_vat_return_period: Optional[str]
    vat_vat_return_due_date: Optional[datetime]
    vat_tax_periods: Optional[str]
    vat_license_holder_name: Optional[str]
    vat_license_issuing_authority: Optional[str]
    vat_license_number: Optional[str]
    vat_date_of_issue: Optional[datetime]
    vat_version_number: Optional[str]


class CorporateTaxSchema(BaseDocSchema):
    ct_certificate_title: Optional[str]
    ct_issuing_authority: Optional[str]
    ct_trn: Optional[str]
    ct_legal_name_ar: Optional[str]
    ct_legal_name_en: Optional[str]
    ct_registered_address: Optional[str]
    ct_contact_number: Optional[str]
    ct_effective_registration_date: Optional[datetime]
    ct_tax_period: Optional[str]

    ct_first_period_start_date: Optional[datetime]
    ct_first_period_end_date: Optional[datetime]
    ct_first_return_due_date: Optional[datetime]

    ct_license_holder_name: Optional[str]
    ct_license_authority: Optional[str]
    ct_license_number: Optional[str]
    ct_license_issue_date: Optional[datetime]

    ct_version_number: Optional[str]


class TradeLicenseSchema(BaseDocSchema):
    tl_license_number: Optional[str]
    tl_membership_number: Optional[str]
    tl_registration_number: Optional[str]

    tl_business_name_ar: Optional[str]
    tl_business_name_en: Optional[str]

    tl_legal_status: Optional[str]
    tl_activities: Optional[str]

    tl_issue_date: Optional[datetime]
    tl_expiry_date: Optional[datetime]
    tl_membership_since: Optional[datetime]


DOC_SCHEMA_MAP = {
    "vat_certificate": VATCertificateSchema,
    "ct_certificate": CorporateTaxSchema,
    "trade_license": TradeLicenseSchema,
}
