from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel


class BaseDocSchema(BaseModel):
    doc_type: Optional[str]
    file_name: str
    file_url: str
    expiry_date: Optional[datetime]
    filing_date: Optional[datetime]
    batch_start_date: Optional[datetime]
    company_address: Optional[str]

    generic_title: Optional[str]
    generic_document_number: Optional[str]
    generic_action_dates: Optional[list]
    generic_parties: Optional[list]

    uploaded_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class UpdateUserDocSchema(BaseModel):
    file_name: Optional[str] = None
    doc_type: Optional[str] = None

    expiry_date: Optional[datetime] = None
    filing_date: Optional[datetime] = None
    batch_start_date: Optional[datetime] = None

    generic_title: Optional[str] = None
    generic_document_number: Optional[str] = None
    generic_action_dates: Optional[List[str]] = None
    generic_parties: Optional[List[str]] = None

    class Config:
        orm_mode = True


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
    vat_batch_one: Optional[str]
    vat_batch_two: Optional[str]
    vat_batch_three: Optional[str]
    vat_batch_four: Optional[str]


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


class PassportSchema(BaseDocSchema):
    passport_number: Optional[str]
    passport_name: Optional[str]
    passport_date_of_birth: Optional[datetime]
    passport_issue_date: Optional[datetime]
    passport_expiry_date: Optional[datetime]


class EmiratesIDSchema(BaseDocSchema):
    emirates_id_number: Optional[str]
    emirates_id_name: Optional[str]
    emirates_id_date_of_birth: Optional[datetime]
    emirates_id_issue_date: Optional[datetime]
    emirates_id_expiry_date: Optional[datetime]


DOC_SCHEMA_MAP = {
    "vat_certificate": VATCertificateSchema,
    "ct_certificate": CorporateTaxSchema,
    "trade_license": TradeLicenseSchema,
    "passport": PassportSchema,
    "emirates_id": EmiratesIDSchema,
}
