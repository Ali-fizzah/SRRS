"""INGEST job: load the files of one upload (plan §10, §7). Registered with the queue."""

from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import write_audit
from app.ingestion.loader import load_upload
from app.jobs.queue import FAILURE_HANDLERS, HANDLERS, ReportProgress
from app.models import JobRun, UploadFile, ValidationError
from app.models.enums import JobType, UploadStatus


def _uploads(db: Session, job: JobRun) -> list[UploadFile]:
    ids = job.params["upload_ids"]
    return list(
        db.scalars(select(UploadFile).where(UploadFile.id.in_(ids)).order_by(UploadFile.id))
    )


def run_ingest(db: Session, job: JobRun, report: ReportProgress) -> dict[str, Any]:
    uploads = _uploads(db, job)
    files = [(u, Path(u.stored_path).read_bytes()) for u in uploads]
    report(10)
    summaries = load_upload(db, files, job.created_by, report)
    return {
        "uploads": [
            {
                "upload_id": s.upload_id,
                "template": s.template.value,
                "status": s.status.value,
                "total_rows": s.total_rows,
                "accepted_rows": s.accepted_rows,
                "rejected_rows": s.rejected_rows,
            }
            for s in summaries
        ]
    }


def ingest_failed(db: Session, job: JobRun, message: str) -> None:
    """Nothing was loaded. Finish the files as REJECTED so they cannot block the month-end
    checklist, which needs every upload in a final state (plan §5.8 item 1)."""
    for upload in _uploads(db, job):
        upload.status = UploadStatus.REJECTED
        db.add(
            ValidationError(
                upload_file_id=upload.id,
                row_number=1,
                error_code="E009",
                message=f"The upload could not be processed: {message}",
            )
        )
        write_audit(
            db,
            user_id=job.created_by,
            action="UPLOAD_FAILED",
            entity_type="upload_file",
            entity_id=upload.id,
            after={"job_id": job.id, "error": message},
        )


HANDLERS[JobType.INGEST] = run_ingest
FAILURE_HANDLERS[JobType.INGEST] = ingest_failed
