from pydantic import BaseModel
from typing import Optional


class ReportCreate(BaseModel):
    report_name: str
    file_path: str


class ReportOut(BaseModel):
    id: int
    report_name: str
    file_path: str

    class Config:
        from_attributes = True
