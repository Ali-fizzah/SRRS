"""Response bodies for POST /uploads and GET /jobs/{id} (plan §8, §10)."""

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
