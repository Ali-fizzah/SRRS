"""Background job status (plan §8 Jobs: any signed-in user, §10)."""

from fastapi import APIRouter

from app.api.errors import ApiError
from app.auth.deps import AuthenticatedUser, DbSession
from app.models import JobRun
from app.schemas.uploads import JobOut

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/{job_id}", response_model=JobOut)
def get_job(job_id: int, db: DbSession, _: AuthenticatedUser) -> JobRun:
    job = db.get(JobRun, job_id)
    if job is None:
        raise ApiError(404, "NOT_FOUND", f"Job {job_id} does not exist.")
    return job
