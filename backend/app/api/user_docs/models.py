from sqlalchemy import Column, Integer, ForeignKey, String, DateTime
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from ...core.database import Base


class UserDocs(Base):
    __tablename__ = "user_docs"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    doc_type = Column(String, nullable=True, index=True)

    file_name = Column(String, nullable=False)
    file_url = Column(String, nullable=False)

    expiry_date = Column(DateTime(timezone=True), nullable=True)
    filing_date = Column(DateTime(timezone=True), nullable=True)
    batch_start_date = Column(DateTime(timezone=True), nullable=True)

    company_address = Column(String, nullable=True)

    uploaded_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user = relationship("User", back_populates="documents")

    legal_name = Column(String, nullable=True)

    # VAT Certificate specific fields
    vat_certificate_title = Column(String, nullable=True)
    vat_issuing_authority = Column(String, nullable=True)
    vat_tax_registration_number = Column(String, nullable=True)
    vat_legal_name_arabic = Column(String, nullable=True)
    vat_legal_name_english = Column(String, nullable=True)
    vat_registered_address = Column(String, nullable=True)
    vat_contact_number = Column(String, nullable=True)
    vat_effective_registration_date = Column(DateTime(timezone=True), nullable=True)
    vat_first_vat_return_period = Column(String, nullable=True)
    vat_vat_return_due_date = Column(DateTime(timezone=True), nullable=True)
    vat_tax_periods = Column(String, nullable=True)
    vat_license_holder_name = Column(String, nullable=True)
    vat_license_issuing_authority = Column(String, nullable=True)
    vat_license_number = Column(String, nullable=True)
    vat_date_of_issue = Column(DateTime(timezone=True), nullable=True)
    vat_version_number = Column(String, nullable=True)
    vat_batch_one = Column(String, nullable=True)
    vat_batch_two = Column(String, nullable=True)
    vat_batch_three = Column(String, nullable=True)
    vat_batch_four = Column(String, nullable=True)

    # Corporate Tax Certificate fields
    ct_certificate_title = Column(String, nullable=True)
    ct_issuing_authority = Column(String, nullable=True)
    ct_trn = Column(String, nullable=True)
    ct_legal_name_ar = Column(String, nullable=True)
    ct_legal_name_en = Column(String, nullable=True)
    ct_registered_address = Column(String, nullable=True)
    ct_contact_number = Column(String, nullable=True)
    ct_effective_registration_date = Column(DateTime(timezone=True), nullable=True)
    ct_tax_period = Column(String, nullable=True)

    # First Corporate Tax Period
    ct_first_period_start_date = Column(DateTime(timezone=True), nullable=True)
    ct_first_period_end_date = Column(DateTime(timezone=True), nullable=True)
    ct_first_return_due_date = Column(DateTime(timezone=True), nullable=True)

    # License information (nested table in PDF)
    ct_license_holder_name = Column(String, nullable=True)
    ct_license_authority = Column(String, nullable=True)
    ct_license_number = Column(String, nullable=True)
    ct_license_issue_date = Column(DateTime(timezone=True), nullable=True)

    # Certificate metadata
    ct_version_number = Column(String, nullable=True)

    # Trade License Certificate fields
    tl_license_number = Column(String, nullable=True)
    tl_membership_number = Column(String, nullable=True)
    tl_registration_number = Column(String, nullable=True)

    tl_business_name_ar = Column(String, nullable=True)
    tl_business_name_en = Column(String, nullable=True)

    tl_legal_status = Column(String, nullable=True)  # LLC, Sole Establishment, etc.

    tl_activities = Column(String, nullable=True)  # store comma separated list or JSON

    tl_issue_date = Column(DateTime(timezone=True), nullable=True)
    tl_expiry_date = Column(DateTime(timezone=True), nullable=True)
    tl_membership_since = Column(DateTime(timezone=True), nullable=True)

    # Passport fields
    passport_number = Column(String, nullable=True)
    passport_name = Column(String, nullable=True)
    passport_date_of_birth = Column(DateTime(timezone=True), nullable=True)
    passport_issue_date = Column(DateTime(timezone=True), nullable=True)
    passport_expiry_date = Column(DateTime(timezone=True), nullable=True)

    # Emirates ID fields
    emirates_id_number = Column(String, nullable=True)
    emirates_id_name = Column(String, nullable=True)
    emirates_id_date_of_birth = Column(DateTime(timezone=True), nullable=True)
    emirates_id_issue_date = Column(DateTime(timezone=True), nullable=True)
    emirates_id_expiry_date = Column(DateTime(timezone=True), nullable=True)
