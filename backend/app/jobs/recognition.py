"""RECOGNITION job: generate revenue schedules (plan §5.4, §10). Registered with the queue."""

from dataclasses import asdict
from typing import Any

from sqlalchemy.orm import Session

from app.jobs.queue import HANDLERS, ReportProgress
from app.models import JobRun
from app.models.enums import JobType
from app.services.recognition_run import run_recognition


def run_recognition_job(db: Session, job: JobRun, report: ReportProgress) -> dict[str, Any]:
    summary = run_recognition(db, job.created_by, job.id, report)
    return {"period_key": job.params["period_key"], **asdict(summary)}


HANDLERS[JobType.RECOGNITION] = run_recognition_job
