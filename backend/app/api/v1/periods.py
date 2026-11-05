"""Accounting periods, close workflow and engine runs (plan §8 Periods and Engine)."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.api.errors import ApiError
from app.api.listing import Listing, Page, apply_sort, list_response
from app.api.v1.stubs import stub
from app.audit import write_audit
from app.auth.deps import CurrentUser, DbSession, get_current_user, require_role
from app.auth.roles import Role
from app.jobs.queue import enqueue
from app.models import AccountingPeriod
from app.models.enums import JobType, PeriodStatus
from app.schemas.contracts import JobAccepted, PeriodOut

router = APIRouter(prefix="/periods", tags=["periods"])


# §8 lists no role for reading periods; the dashboard shows the current period to everyone.
@router.get(
    "",
    response_model=Page[PeriodOut],
    responses={200: {"content": {"text/csv": {}}}},
    dependencies=[Depends(get_current_user)],
)
def list_periods(db: DbSession, params: Listing, status: PeriodStatus | None = None) -> Any:
    """Accounting periods in order; `status=OPEN` finds the current period (D6)."""
    statement = select(
        AccountingPeriod.id,
        AccountingPeriod.period_key,
        AccountingPeriod.start_date,
        AccountingPeriod.end_date,
        AccountingPeriod.status,
    )
    if status is not None:
        statement = statement.where(AccountingPeriod.status == status)
    statement = apply_sort(
        statement,
        params.sort,
        {"period_key": AccountingPeriod.period_key, "status": AccountingPeriod.status},
        [AccountingPeriod.period_key],
    )
    return list_response(db, statement, params, PeriodOut, "periods.csv")


stub(router, "GET", "/{key}/checklist", None, "P5-T1")
stub(router, "POST", "/{key}/start-close", Role.ACCOUNTANT, "P5-T1")
stub(router, "POST", "/{key}/close", Role.APPROVER, "P5-T1")
stub(router, "POST", "/{key}/reopen", Role.ADMIN, "P5-T1")

# Engine
Accountant = Annotated[CurrentUser, Depends(require_role(Role.ACCOUNTANT))]


def _require_current(db: DbSession, key: str, what: str) -> None:
    status = db.scalar(select(AccountingPeriod.status).where(AccountingPeriod.period_key == key))
    if status is None:
        raise ApiError(404, "NOT_FOUND", f"Period {key} does not exist.")
    if status not in (PeriodStatus.OPEN, PeriodStatus.CLOSING):
        raise ApiError(
            409,
            "PERIOD_NOT_CURRENT",
            f"Period {key} is {status.value}; {what} only for the current period.",
        )


@router.post("/{key}/recognition-run", response_model=JobAccepted, status_code=202)
def start_recognition_run(key: str, db: DbSession, user: Accountant) -> JobAccepted:
    """Queue a RECOGNITION job for the current period (plan §5.4, §10).

    OPEN or CLOSING: during close the period is still current and journals are still
    generated (§5.8). Earlier and later periods are refused.
    """
    _require_current(db, key, "recognition runs")
    job = enqueue(db, JobType.RECOGNITION, {"period_key": key}, user.id)
    write_audit(
        db,
        user_id=user.id,
        action="RECOGNITION_RUN_REQUESTED",
        entity_type="accounting_period",
        entity_id=key,
        after={"job_id": job.id},
    )
    db.commit()
    return JobAccepted(job_id=job.id)


@router.post("/{key}/journals/generate", response_model=JobAccepted, status_code=202)
def start_journal_generation(key: str, db: DbSession, user: Accountant) -> JobAccepted:
    """Queue a JOURNALS job for the current period (plan §5.7, §10)."""
    _require_current(db, key, "journals are generated")
    job = enqueue(db, JobType.JOURNALS, {"period_key": key}, user.id)
    write_audit(
        db,
        user_id=user.id,
        action="JOURNALS_REQUESTED",
        entity_type="accounting_period",
        entity_id=key,
        after={"job_id": job.id},
    )
    db.commit()
    return JobAccepted(job_id=job.id)
