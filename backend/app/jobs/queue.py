"""PostgreSQL-backed job queue (plan §10, D10).

The API calls `enqueue` inside its own transaction. The worker calls `run_next_job`:
- the claim commits RUNNING straight away, so the job is visible as started;
- the handler's work and the DONE status commit together, so a job never says DONE
  with part of its data missing;
- progress goes through its own short session, so it is visible while the handler's
  transaction is still open.
"""

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from app.models import JobRun
from app.models.enums import JobStatus, JobType

log = logging.getLogger("revrec.worker")

ReportProgress = Callable[[int], None]
# handler(session, job, report) -> the job's result. The queue commits the session.
Handler = Callable[[Session, JobRun, ReportProgress], dict[str, Any]]
# on_failure(session, job, message): tidy up after a failed run. The queue commits.
FailureHandler = Callable[[Session, JobRun, str], None]

HANDLERS: dict[JobType, Handler] = {}
FAILURE_HANDLERS: dict[JobType, FailureHandler] = {}


def enqueue(
    db: Session, job_type: JobType, params: dict[str, Any], created_by: int | None
) -> JobRun:
    """Add a QUEUED job to the caller's transaction."""
    job = JobRun(job_type=job_type, params=params, created_by=created_by)
    db.add(job)
    db.flush()
    return job


def claim_next(db: Session) -> JobRun | None:
    """Lock the oldest QUEUED job. SKIP LOCKED: two workers never get the same job."""
    job = db.scalar(
        select(JobRun)
        .where(JobRun.status == JobStatus.QUEUED)
        .order_by(JobRun.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if job is not None:
        job.status = JobStatus.RUNNING
        job.started_at = datetime.now(UTC)
    return job


def run_next_job(factory: sessionmaker[Session]) -> bool:
    """Run one job if there is one. Returns False when the queue is empty."""
    with factory() as db:
        job = claim_next(db)
        if job is None:
            return False
        db.commit()
        job_id, job_type = job.id, job.job_type

    def report(progress: int) -> None:
        with factory() as progress_db:
            progress_db.execute(update(JobRun).where(JobRun.id == job_id).values(progress=progress))
            progress_db.commit()

    log.info("job %s (%s) started", job_id, job_type.value)
    try:
        with factory() as db:
            job = db.get_one(JobRun, job_id)
            result = HANDLERS[job_type](db, job, report)
            job.status = JobStatus.DONE
            job.progress = 100
            job.result = result
            job.finished_at = datetime.now(UTC)
            db.commit()
    except Exception as exc:  # any failure must end as FAILED, not a job stuck in RUNNING
        log.exception("job %s failed", job_id)
        _mark_failed(factory, job_id, job_type, f"{type(exc).__name__}: {exc}")
    else:
        log.info("job %s done", job_id)
    return True


def _mark_failed(
    factory: sessionmaker[Session], job_id: int, job_type: JobType, message: str
) -> None:
    with factory() as db:
        job = db.get_one(JobRun, job_id)
        job.status = JobStatus.FAILED
        job.error = message
        job.finished_at = datetime.now(UTC)
        on_failure = FAILURE_HANDLERS.get(job_type)
        if on_failure is not None:
            on_failure(db, job, message)
        db.commit()
