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
    is_processing: Optional[bool] = None

    model_config = {"from_attributes": True}


class UpdateUserDocSchema(BaseModel):
    file_name: Optional[str] = None
    doc_type: Optional[str] = None

    expiry_date: Optional[datetime] = None
    filing_date: Optional[datetime] = None
    batch_start_date: Optional[datetime] = None
    company_address: Optional[str] = None

    generic_title: Optional[str] = None
    generic_document_number: Optional[str] = None
    generic_action_dates: Optional[List[str]] = None
    generic_parties: Optional[List[str]] = None

    # VAT fields
    vat_certificate_title: Optional[str] = None
    vat_issuing_authority: Optional[str] = None
    vat_tax_registration_number: Optional[str] = None
    vat_legal_name_arabic: Optional[str] = None
    vat_legal_name_english: Optional[str] = None
    vat_registered_address: Optional[str] = None
    vat_contact_number: Optional[str] = None
    vat_effective_registration_date: Optional[datetime] = None
    vat_first_vat_return_period: Optional[str] = None
    vat_vat_return_due_date: Optional[datetime] = None
    vat_tax_periods: Optional[str] = None
    vat_license_holder_name: Optional[str] = None
    vat_license_issuing_authority: Optional[str] = None
    vat_license_number: Optional[str] = None
    vat_date_of_issue: Optional[datetime] = None
    vat_version_number: Optional[str] = None
    vat_batch_one: Optional[str] = None
    vat_batch_two: Optional[str] = None
    vat_batch_three: Optional[str] = None
    vat_batch_four: Optional[str] = None

    # CT fields
    ct_certificate_title: Optional[str] = None
    ct_issuing_authority: Optional[str] = None
    ct_trn: Optional[str] = None
    ct_legal_name_ar: Optional[str] = None
    ct_legal_name_en: Optional[str] = None
    ct_registered_address: Optional[str] = None
    ct_contact_number: Optional[str] = None
    ct_effective_registration_date: Optional[datetime] = None
    ct_tax_period: Optional[str] = None
    ct_first_period_start_date: Optional[datetime] = None
    ct_first_period_end_date: Optional[datetime] = None
    ct_first_return_due_date: Optional[datetime] = None
    ct_license_holder_name: Optional[str] = None
    ct_license_authority: Optional[str] = None
    ct_license_number: Optional[str] = None
    ct_license_issue_date: Optional[datetime] = None
    ct_version_number: Optional[str] = None

    # Trade License fields
    tl_license_number: Optional[str] = None
    tl_membership_number: Optional[str] = None
    tl_registration_number: Optional[str] = None
    tl_business_name_ar: Optional[str] = None
    tl_business_name_en: Optional[str] = None
    tl_legal_status: Optional[str] = None
    tl_activities: Optional[str] = None
    tl_issue_date: Optional[datetime] = None
    tl_expiry_date: Optional[datetime] = None
    tl_membership_since: Optional[datetime] = None

    # Passport fields
    passport_number: Optional[str] = None
    passport_name: Optional[str] = None
    passport_date_of_birth: Optional[datetime] = None
    passport_issue_date: Optional[datetime] = None
    passport_expiry_date: Optional[datetime] = None

    # Emirates ID fields
    emirates_id_number: Optional[str] = None
    emirates_id_name: Optional[str] = None
    emirates_id_date_of_birth: Optional[datetime] = None
    emirates_id_issue_date: Optional[datetime] = None
    emirates_id_expiry_date: Optional[datetime] = None

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


class SellerProfileSelect(BaseModel):
    doc_id: int


class SellerProfileOut(BaseModel):
    id: int
    user_id: int
    doc_id: int
    doc_type: Optional[str] = None
    company_name_en: str
    company_name_ar: Optional[str] = None
    company_trn: str
    company_address: Optional[str] = None
    vat_registered: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
