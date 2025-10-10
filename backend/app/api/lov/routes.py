from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.api.companies.models import Company
from .enums import BatchType

router = APIRouter(prefix="/lovs", tags=["LOV"])

@router.get("/filing-batch")
def get_filing_batches():
    """
    Returns a list of batch types for dropdown
    """
    batches = [{"id": i, "label": batch.value} for i, batch in enumerate(BatchType, start=1)]
    return batches

@router.get("/companies")
def get_companies(db: Session = Depends(get_db)):
    """
    Returns all companies from DB in id, label format
    """
    companies = db.query(Company).all()
    return [{"id": company.id, "label": company.name} for company in companies]
