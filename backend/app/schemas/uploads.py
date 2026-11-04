"""Response bodies for /uploads and /jobs (plan §8, §10)."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models.enums import JobStatus, JobType, UploadStatus, UploadTemplate


class AcceptedFile(BaseModel):
    upload_id: int
    filename: str
    template: UploadTemplate
    status: UploadStatus


class UploadAccepted(BaseModel):
    job_id: int
    files: list[AcceptedFile]


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_type: JobType
    status: JobStatus
    progress: int
    result: dict[str, Any] | None
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class UploadOut(BaseModel):
    id: int
    template: UploadTemplate
    original_filename: str
    period_key: str
    status: UploadStatus
    total_rows: int
    accepted_rows: int
    rejected_rows: int
    uploaded_by: str  # the uploader's name
    created_at: datetime


class UploadPage(BaseModel):
    items: list[UploadOut]
    total: int
    page: int
    page_size: int


class ValidationErrorOut(BaseModel):
    id: int
    row_number: int
    column_name: str | None
    error_code: str
    message: str
    raw_value: str | None


class ValidationErrorPage(BaseModel):
    items: list[ValidationErrorOut]
    total: int
    page: int
    page_size: int
