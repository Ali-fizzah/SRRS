"""JOURNALS job: generate a period's journal batch (plan §5.7, §10). Registered with the queue."""

from dataclasses import asdict
from typing import Any

from sqlalchemy.orm import Session

from app.jobs.queue import HANDLERS, ReportProgress
from app.models import JobRun
from app.models.enums import JobType
from app.services.journals import generate_journals


def run_journals_job(db: Session, job: JobRun, report: ReportProgress) -> dict[str, Any]:
    if job.created_by is None:
        raise ValueError("a journal batch needs the user who generated it (D13)")
    return asdict(generate_journals(db, job.params["period_key"], job.created_by, report))


HANDLERS[JobType.JOURNALS] = run_journals_job
