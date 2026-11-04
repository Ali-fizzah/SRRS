"""File uploads and their validation logs (plan §8 Uploads: UPLOADER)."""

import hashlib
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File
from fastapi import UploadFile as IncomingFile
from sqlalchemy import select

from app.api.errors import ApiError
from app.api.v1.stubs import stub
from app.audit import write_audit
from app.auth.deps import CurrentUser, DbSession, require_role
from app.auth.roles import Role
from app.config import get_settings
from app.ingestion.parser import detect_template
from app.jobs.queue import enqueue
from app.models import AccountingPeriod, UploadFile
from app.models.enums import JobType, PeriodStatus, UploadStatus
from app.schemas.uploads import AcceptedFile, UploadAccepted

router = APIRouter(prefix="/uploads", tags=["uploads"])
Uploader = Annotated[CurrentUser, Depends(require_role(Role.UPLOADER))]


def _read(file: IncomingFile, limit: int) -> bytes:
    content = file.file.read(limit + 1)
    if len(content) > limit:
        raise ApiError(
            413,
            "FILE_TOO_LARGE",
            f"{file.filename} is larger than the {limit // (1024 * 1024)} MB limit.",
        )
    return content


@router.post("", response_model=UploadAccepted, status_code=202)
def create_upload(
    files: Annotated[list[IncomingFile], File()], db: DbSession, user: Uploader
) -> UploadAccepted:
    """Store the files and queue an INGEST job; poll GET /jobs/{job_id} for the outcome."""
    settings = get_settings()
    period = db.scalar(
        select(AccountingPeriod.period_key).where(AccountingPeriod.status == PeriodStatus.OPEN)
    )
    if period is None:  # §5.8: a period in CLOSING blocks new uploads
        raise ApiError(409, "NO_OPEN_PERIOD", "Uploads are blocked until the next period opens.")

    # Check every file first, so a bad request stores nothing.
    incoming = []
    for file in files:
        name = Path(file.filename or "upload").name[:255]  # display only, never a storage path
        content = _read(file, settings.max_upload_bytes)
        template = detect_template(content, name)
        if template is None:
            raise ApiError(
                422,
                "UNKNOWN_TEMPLATE",
                f"{name} does not match any template. Keep the template's header row, or put "
                "the template name in the filename (for example contracts_march.csv).",
            )
        incoming.append((name, content, template))

    folder = Path(settings.upload_dir)
    folder.mkdir(parents=True, exist_ok=True)
    records = []
    for name, content, template in incoming:
        suffix = Path(name).suffix.lower()
        path = folder / f"{uuid.uuid4().hex}{suffix if suffix in ('.csv', '.xlsx') else '.dat'}"
        path.write_bytes(content)
        record = UploadFile(
            template=template,
            original_filename=name,
            sha256=hashlib.sha256(content).hexdigest(),
            stored_path=str(path),
            uploaded_by=user.id,
            period_key=period,
            status=UploadStatus.RECEIVED,
        )
        db.add(record)
        records.append(record)
    db.flush()

    job = enqueue(db, JobType.INGEST, {"upload_ids": [r.id for r in records]}, user.id)
    for record in records:
        write_audit(
            db,
            user_id=user.id,
            action="UPLOAD_RECEIVED",
            entity_type="upload_file",
            entity_id=record.id,
            after={
                "filename": record.original_filename,
                "template": record.template.value,
                "sha256": record.sha256,
                "job_id": job.id,
            },
        )
    db.commit()
    return UploadAccepted(
        job_id=job.id,
        files=[
            AcceptedFile(
                upload_id=r.id,
                filename=r.original_filename,
                template=r.template,
                status=UploadStatus.RECEIVED,
            )
            for r in records
        ],
    )


stub(router, "GET", "", Role.UPLOADER, "P1-T10")
stub(router, "GET", "/{upload_id}", Role.UPLOADER, "P1-T10")
stub(router, "GET", "/{upload_id}/errors", Role.UPLOADER, "P1-T10")
stub(router, "GET", "/{upload_id}/file", Role.UPLOADER, "P1-T10")
