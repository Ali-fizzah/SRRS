"""Background job status (plan §8 Jobs: any signed-in user)."""

from fastapi import APIRouter

from app.api.v1.stubs import stub

router = APIRouter(prefix="/jobs", tags=["jobs"])

stub(router, "GET", "/{job_id}", None, "P1-T9")
