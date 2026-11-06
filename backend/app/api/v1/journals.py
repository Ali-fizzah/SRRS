"""Journal batches and entries (plan §5.7, §8 Journals: view ACCOUNTANT, approve/post APPROVER)."""

from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import Select, exists, func, select
from sqlalchemy.orm import aliased

from app.api.errors import ApiError
from app.api.listing import Listing, Page, PeriodFilter, apply_sort, list_response, page_of
from app.auth.deps import CurrentUser, DbSession, require_role
from app.auth.roles import Role
from app.models import (
    AccountingPeriod,
    Contract,
    ContractLine,
    ContractVersion,
    GlAccount,
    JournalBatch,
    JournalEntry,
    JournalLine,
    PerformanceObligation,
    Product,
    User,
)
from app.models.enums import BatchStatus, JournalEntryType
from app.schemas.journals import (
    JournalBatchDetail,
    JournalBatchOut,
    JournalLineOut,
    ReverseIn,
    ReverseOut,
    SendBackIn,
)
from app.services.journals import (
    JournalRuleError,
    approve_batch,
    post_batch,
    reverse_entry,
    send_back_batch,
)

router = APIRouter(tags=["journals"])

CanView = [Depends(require_role(Role.ACCOUNTANT))]
Approver = Annotated[CurrentUser, Depends(require_role(Role.APPROVER))]
# A reversal is a new entry that still goes through approve/post, so the preparer
# (ACCOUNTANT) books it and an APPROVER approves it.
Accountant = Annotated[CurrentUser, Depends(require_role(Role.ACCOUNTANT))]
CSV: dict[int | str, dict[str, Any]] = {200: {"content": {"text/csv": {}}}}


def _batches() -> Select[Any]:
    generated, approved, posted = aliased(User), aliased(User), aliased(User)
    entry_count = (
        select(func.count(JournalEntry.id))
        .where(JournalEntry.batch_id == JournalBatch.id)
        .scalar_subquery()
    )
    return (
        select(
            JournalBatch.id,
            AccountingPeriod.period_key,
            JournalBatch.batch_no,
            JournalBatch.status,
            generated.full_name.label("generated_by_name"),
            JournalBatch.generated_by.label("generated_by_id"),
            approved.full_name.label("approved_by_name"),
            JournalBatch.approved_at,
            posted.full_name.label("posted_by_name"),
            JournalBatch.posted_at,
            JournalBatch.total_debit,
            JournalBatch.total_credit,
            entry_count.label("entry_count"),
        )
        .join(AccountingPeriod, AccountingPeriod.id == JournalBatch.period_id)
        .join(generated, generated.id == JournalBatch.generated_by)
        .outerjoin(approved, approved.id == JournalBatch.approved_by)
        .outerjoin(posted, posted.id == JournalBatch.posted_by)
    )


def journal_lines_query() -> Select[Any]:
    """Journal lines with everything a reader needs to trace them (§5.7)."""
    reversal = aliased(JournalEntry)
    first_of_entry = (
        func.row_number().over(partition_by=JournalLine.entry_id, order_by=JournalLine.id) == 1
    )
    can_reverse = (
        (JournalBatch.status == BatchStatus.POSTED)
        & (JournalEntry.entry_type != JournalEntryType.REVERSAL)
        & ~exists().where(reversal.reverses_entry_id == JournalEntry.id)
    )
    return (
        select(
            JournalLine.id,
            JournalLine.entry_id,
            JournalEntry.entry_type,
            JournalEntry.entry_date,
            JournalEntry.description,
            JournalEntry.contract_id,
            Contract.contract_code,
            ContractVersion.version_no,
            JournalEntry.source_type,
            JournalEntry.source_id,
            JournalEntry.source_upload_id,
            JournalEntry.source_row,
            JournalEntry.reverses_entry_id,
            GlAccount.account_code,
            GlAccount.name.label("account_name"),
            JournalLine.debit,
            JournalLine.credit,
            Product.product_code,
            ContractLine.line_no,
            JournalEntry.batch_id,
            JournalBatch.batch_no,
            JournalBatch.status.label("batch_status"),
            AccountingPeriod.period_key,
            first_of_entry.label("first_of_entry"),
            can_reverse.label("can_reverse"),
        )
        .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
        .join(JournalBatch, JournalBatch.id == JournalEntry.batch_id)
        .join(AccountingPeriod, AccountingPeriod.id == JournalBatch.period_id)
        .join(Contract, Contract.id == JournalEntry.contract_id)
        .join(ContractVersion, ContractVersion.id == JournalEntry.contract_version_id)
        .join(GlAccount, GlAccount.id == JournalLine.account_id)
        .outerjoin(Product, Product.id == JournalLine.product_id)
        .outerjoin(
            PerformanceObligation,
            PerformanceObligation.id == JournalLine.performance_obligation_id,
        )
        .outerjoin(ContractLine, ContractLine.id == PerformanceObligation.contract_line_id)
    )


JOURNAL_LINE_SORTS: dict[str, Any] = {
    "entry_id": JournalLine.entry_id,
    "entry_type": JournalEntry.entry_type,
    "entry_date": JournalEntry.entry_date,
    "contract_code": Contract.contract_code,
    "account_code": GlAccount.account_code,
    "debit": JournalLine.debit,
    "credit": JournalLine.credit,
    "period_key": AccountingPeriod.period_key,
}


@router.get(
    "/journal-batches", response_model=Page[JournalBatchOut], responses=CSV, dependencies=CanView
)
def list_batches(
    db: DbSession,
    params: Listing,
    status: BatchStatus | None = None,
    period_from: PeriodFilter = None,
    period_to: PeriodFilter = None,
) -> Any:
    """Batches by period and status (plan §9). Newest first."""
    statement = _batches()
    if status is not None:
        statement = statement.where(JournalBatch.status == status)
    if period_from is not None:
        statement = statement.where(AccountingPeriod.period_key >= period_from)
    if period_to is not None:
        statement = statement.where(AccountingPeriod.period_key <= period_to)
    statement = apply_sort(
        statement,
        params.sort,
        {
            "period_key": AccountingPeriod.period_key,
            "batch_no": JournalBatch.batch_no,
            "status": JournalBatch.status,
            "total_debit": JournalBatch.total_debit,
            "total_credit": JournalBatch.total_credit,
        },
        [AccountingPeriod.period_key.desc(), JournalBatch.batch_no.desc()],
    )
    return list_response(db, statement, params, JournalBatchOut, "journal_batches.csv")


def _batch_out(db: DbSession, batch_id: int) -> JournalBatchOut:
    row = db.execute(_batches().where(JournalBatch.id == batch_id)).first()
    if row is None:
        raise ApiError(404, "NOT_FOUND", f"Journal batch {batch_id} does not exist.")
    return JournalBatchOut.model_validate(dict(row._mapping))


@router.get(
    "/journal-batches/{batch_id}",
    response_model=JournalBatchDetail,
    responses=CSV,
    dependencies=CanView,
)
def get_batch(batch_id: int, db: DbSession, params: Listing) -> Any:
    """The batch with its entries and lines, and the balance worked out from the lines."""
    batch = _batch_out(db, batch_id)
    statement = apply_sort(
        journal_lines_query().where(JournalEntry.batch_id == batch_id),
        params.sort,
        JOURNAL_LINE_SORTS,
        [JournalLine.entry_id, JournalLine.id],
    )
    if params.format == "csv":
        return list_response(db, statement, params, JournalLineOut, f"batch_{batch_id}.csv")
    rows, total = page_of(db, statement, params)
    debit, credit = db.execute(
        select(
            func.coalesce(func.sum(JournalLine.debit), 0),
            func.coalesce(func.sum(JournalLine.credit), 0),
        )
        .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
        .where(JournalEntry.batch_id == batch_id)
    ).one()
    return JournalBatchDetail(
        batch=batch,
        balanced=debit == credit,
        items=[JournalLineOut.model_validate(dict(row._mapping)) for row in rows],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )


def _apply[T](db: DbSession, action: Callable[[], T]) -> T:
    """Run one lifecycle action in its own transaction, with the §8 error shape."""
    try:
        result = action()
    except JournalRuleError as exc:
        # Rules refuse before writing, and an uncommitted session is discarded with the request.
        raise ApiError(exc.status, exc.code, exc.message) from exc
    db.commit()
    return result


@router.post("/journal-batches/{batch_id}/approve", response_model=JournalBatchOut)
def approve(batch_id: int, db: DbSession, user: Approver) -> JournalBatchOut:
    """DRAFT -> APPROVED. The user who generated the batch cannot approve it (D13)."""
    _apply(db, lambda: approve_batch(db, batch_id, user.id))
    return _batch_out(db, batch_id)


@router.post("/journal-batches/{batch_id}/send-back", response_model=JournalBatchOut)
def send_back(
    batch_id: int, db: DbSession, user: Approver, body: SendBackIn | None = None
) -> JournalBatchOut:
    """APPROVED -> DRAFT (§5.7)."""
    reason = body.reason if body else None
    _apply(db, lambda: send_back_batch(db, batch_id, user.id, reason))
    return _batch_out(db, batch_id)


@router.post("/journal-batches/{batch_id}/post", response_model=JournalBatchOut)
def post(batch_id: int, db: DbSession, user: Approver) -> JournalBatchOut:
    """APPROVED -> POSTED. Read-only from here on (§6.3)."""
    _apply(db, lambda: post_batch(db, batch_id, user.id))
    return _batch_out(db, batch_id)


@router.post("/journal-entries/{entry_id}/reverse", response_model=ReverseOut, status_code=201)
def reverse(entry_id: int, body: ReverseIn, db: DbSession, user: Accountant) -> ReverseOut:
    """Book a REVERSAL in a new DRAFT batch of the current period (§5.7)."""
    batch = _apply(db, lambda: reverse_entry(db, entry_id, user.id, body.reason))
    return ReverseOut(batch_id=batch.id)
