"""File uploads and their validation logs (plan §8 Uploads: UPLOADER)."""

import hashlib
import uuid
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File
from fastapi import UploadFile as IncomingFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.errors import ApiError
from app.api.listing import Listing, PeriodFilter, apply_sort, csv_response, page_of
from app.audit import write_audit
from app.auth.deps import CurrentUser, DbSession, require_role
from app.auth.roles import Role
from app.config import get_settings
from app.ingestion.parser import detect_template
from app.jobs.queue import enqueue
from app.models import AccountingPeriod, UploadFile, User, ValidationError
from app.models.enums import JobType, PeriodStatus, UploadStatus
from app.schemas.uploads import (
    AcceptedFile,
    UploadAccepted,
    UploadOut,
    UploadPage,
    ValidationErrorOut,
    ValidationErrorPage,
)

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


_UPLOAD_COLUMNS = (
    UploadFile.id,
    UploadFile.template,
    UploadFile.original_filename,
    UploadFile.period_key,
    UploadFile.status,
    UploadFile.total_rows,
    UploadFile.accepted_rows,
    UploadFile.rejected_rows,
    User.full_name.label("uploaded_by"),
    UploadFile.created_at,
)
_UPLOADS = select(*_UPLOAD_COLUMNS).join(User, User.id == UploadFile.uploaded_by)
_UPLOAD_SORTS = {
    "id": UploadFile.id,
    "template": UploadFile.template,
    "original_filename": UploadFile.original_filename,
    "period_key": UploadFile.period_key,
    "status": UploadFile.status,
    "total_rows": UploadFile.total_rows,
    "accepted_rows": UploadFile.accepted_rows,
    "rejected_rows": UploadFile.rejected_rows,
    "uploaded_by": User.full_name,
    "created_at": UploadFile.created_at,
}
_ERROR_SORTS = {
    "row_number": ValidationError.row_number,
    "column_name": ValidationError.column_name,
    "error_code": ValidationError.error_code,
}


def _upload_out(row: Any) -> UploadOut:
    return UploadOut.model_validate(dict(row._mapping))


def _upload_or_404(db: Session, upload_id: int) -> UploadFile:
    upload = db.get(UploadFile, upload_id)
    if upload is None:
        raise ApiError(404, "NOT_FOUND", f"Upload {upload_id} does not exist.")
    return upload


@router.get(
    "",
    response_model=UploadPage,
    responses={200: {"content": {"text/csv": {}}}},
)
def list_uploads(
    db: DbSession,
    _: Uploader,
    params: Listing,
    period_from: PeriodFilter = None,
    period_to: PeriodFilter = None,
) -> Any:
    """Upload history, newest first. §8's customer/contract/product filters do not apply here."""
    statement = _UPLOADS
    if period_from is not None:
        statement = statement.where(UploadFile.period_key >= period_from)
    if period_to is not None:
        statement = statement.where(UploadFile.period_key <= period_to)
    statement = apply_sort(statement, params.sort, _UPLOAD_SORTS, [UploadFile.id.desc()])
    if params.format == "csv":
        return csv_response(
            "uploads.csv",
            [c.key or "" for c in _UPLOAD_COLUMNS],
            db.execute(statement.execution_options(yield_per=1000)),
        )
    rows, total = page_of(db, statement, params)
    return UploadPage(
        items=[_upload_out(r) for r in rows],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )


@router.get("/{upload_id}", response_model=UploadOut)
def get_upload(upload_id: int, db: DbSession, _: Uploader) -> UploadOut:
    row = db.execute(_UPLOADS.where(UploadFile.id == upload_id)).first()
    if row is None:
        raise ApiError(404, "NOT_FOUND", f"Upload {upload_id} does not exist.")
    return _upload_out(row)


@router.get(
    "/{upload_id}/errors",
    response_model=ValidationErrorPage,
    responses={200: {"content": {"text/csv": {}}}},
)
def list_upload_errors(upload_id: int, db: DbSession, _: Uploader, params: Listing) -> Any:
    """The validation log of one upload; `format=csv` downloads all of it (plan §7.1)."""
    _upload_or_404(db, upload_id)
    columns = (
        ValidationError.row_number,
        ValidationError.column_name,
        ValidationError.error_code,
        ValidationError.message,
        ValidationError.raw_value,
    )
    filtered = select(ValidationError.id, *columns).where(
        ValidationError.upload_file_id == upload_id
    )
    statement = apply_sort(
        filtered, params.sort, _ERROR_SORTS, [ValidationError.row_number, ValidationError.id]
    )
    if params.format == "csv":
        return csv_response(
            f"upload_{upload_id}_errors.csv",
            ["upload_id", "row_number", "column_name", "error_code", "message", "raw_value"],
            (
                (upload_id, r.row_number, r.column_name, r.error_code, r.message, r.raw_value)
                for r in db.execute(statement.execution_options(yield_per=1000))
            ),
        )
    rows, total = page_of(db, statement, params)
    return ValidationErrorPage(
        items=[ValidationErrorOut.model_validate(dict(r._mapping)) for r in rows],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )


@router.get("/{upload_id}/file", response_class=FileResponse)
def download_upload_file(upload_id: int, db: DbSession, _: Uploader) -> FileResponse:
    """The original file exactly as it was uploaded (traceability, CLAUDE.md rule 5)."""
    upload = _upload_or_404(db, upload_id)
    path = Path(upload.stored_path)
    if not path.is_file():
        raise ApiError(404, "FILE_MISSING", f"The stored file for upload {upload_id} is missing.")
    return FileResponse(
        path, filename=upload.original_filename, media_type="application/octet-stream"
    )
