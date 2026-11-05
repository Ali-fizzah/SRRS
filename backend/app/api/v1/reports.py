"""Reports (plan §8 Reports: validation log UPLOADER, others ACCOUNTANT). Task P5-T3.

Filters, paging and CSV are server-side. Reports worked out in Python (rollforward, trend, MRR)
page over their finished rows; those rows are one per month, or per contract in a chosen month.
"""

from collections import defaultdict
from collections.abc import Sequence
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import Select, exists, func, or_, select
from sqlalchemy.orm import aliased

from app.api.errors import ApiError
from app.api.listing import (
    Listing,
    ListParams,
    Page,
    PeriodFilter,
    Search,
    apply_sort,
    csv_response,
    list_response,
    page_of,
)
from app.api.v1.journals import journal_lines_query
from app.api.v1.periods import checklist_out
from app.auth.deps import DbSession, require_role
from app.auth.roles import Role
from app.engine.balances import PeriodBalance
from app.engine.money import from_cents, to_cents
from app.engine.mrr import MrrLine, mrr_by_period
from app.engine.periods import iter_periods, period_key
from app.models import (
    AccountingPeriod,
    Contract,
    ContractLine,
    ContractVersion,
    Customer,
    GlAccount,
    JournalBatch,
    JournalEntry,
    JournalLine,
    PerformanceObligation,
    Product,
    RevenueSchedule,
    ScheduleLine,
    UploadFile,
    User,
    ValidationError,
)
from app.models.enums import (
    BatchStatus,
    ContractEventType,
    JournalEntryType,
    PeriodStatus,
    RecognitionMethod,
    ScheduleLineStatus,
)
from app.schemas.reports import (
    CloseStatusPage,
    CloseStatusRow,
    GlSummaryRow,
    JournalRegisterRow,
    MrrArrRow,
    RecognizedVsDeferredRow,
    RevenueSchedulePage,
    RevenueScheduleRow,
    RollforwardRow,
    ValidationLogRow,
)
from app.services.billing import all_balances

router = APIRouter(prefix="/reports", tags=["reports"])

Accountant = [Depends(require_role(Role.ACCOUNTANT))]
Uploader = [Depends(require_role(Role.UPLOADER))]
CSV: dict[int | str, dict[str, Any]] = {200: {"content": {"text/csv": {}}}}
CENT = Decimal("0.01")


def _text_filter(column: Any, value: str) -> Any:
    return column.icontains(value, autoescape=True)


def _contract_filters(
    statement: Select[Any], customer: str | None, contract: str | None
) -> Select[Any]:
    """§8 filters. The statement must have Contract and Customer joined."""
    if customer is not None:
        statement = statement.where(
            or_(
                _text_filter(Customer.customer_code, customer),
                _text_filter(Customer.name, customer),
            )
        )
    if contract is not None:
        statement = statement.where(_text_filter(Contract.contract_code, contract))
    return statement


def _product_filter(column_code: Any, column_name: Any, product: str) -> Any:
    return or_(_text_filter(column_code, product), _text_filter(column_name, product))


def _matching_contract_ids(
    db: DbSession, customer: str | None, contract: str | None, product: str | None
) -> list[int] | None:
    """Contracts matching the filters, or None when no filter applies."""
    if customer is None and contract is None and product is None:
        return None
    statement = _contract_filters(
        select(Contract.id).join(Customer, Customer.id == Contract.customer_id), customer, contract
    )
    if product is not None:
        statement = statement.where(
            exists()
            .where(ContractVersion.contract_id == Contract.id)
            .where(ContractLine.contract_version_id == ContractVersion.id)
            .where(Product.id == ContractLine.product_id)
            .where(_product_filter(Product.product_code, Product.name, product))
        )
    return list(db.scalars(statement))


def _rows_response[Row: BaseModel](
    rows: Sequence[Row], params: ListParams, model: type[Row], filename: str
) -> Any:
    """Answer with rows already worked out in Python: one page, or all of them as CSV."""
    if params.format == "csv":
        fields = [name for name in model.model_fields if name != "id"]
        return csv_response(
            filename, fields, ([getattr(row, name) for name in fields] for row in rows)
        )
    start = (params.page - 1) * params.page_size
    return Page[Row](
        items=list(rows[start : start + params.page_size]),
        total=len(rows),
        page=params.page,
        page_size=params.page_size,
    )


def _sorted_rows[Row: BaseModel](
    rows: list[Row], sort: str | None, allowed: Sequence[str]
) -> list[Row]:
    if sort is None:
        return rows
    name = sort.removeprefix("-")
    if name not in allowed:
        raise ApiError(
            422, "INVALID_SORT", f"Cannot sort by {name!r}.", {"allowed": sorted(allowed)}
        )
    return sorted(rows, key=lambda row: getattr(row, name), reverse=sort.startswith("-"))


# --------------------------------------------------------------------------- revenue schedule


@router.get(
    "/revenue-schedule", response_model=RevenueSchedulePage, responses=CSV, dependencies=Accountant
)
def revenue_schedule(
    db: DbSession,
    params: Listing,
    period_from: PeriodFilter = None,
    period_to: PeriodFilter = None,
    customer: Search = None,
    contract: Search = None,
    product: Search = None,
    status: ScheduleLineStatus | None = None,
) -> Any:
    """Revenue per contract line per month, by service period. Superseded lines are left out."""
    statement = (
        select(
            ScheduleLine.id,
            Contract.id.label("contract_id"),
            Contract.contract_code,
            Customer.name.label("customer_name"),
            ContractVersion.version_no,
            ContractLine.line_no,
            Product.product_code,
            PerformanceObligation.method,
            ScheduleLine.service_period,
            ScheduleLine.posting_period,
            ScheduleLine.is_catch_up,
            ScheduleLine.amount,
            ScheduleLine.status,
        )
        .join(RevenueSchedule, RevenueSchedule.id == ScheduleLine.schedule_id)
        .join(
            PerformanceObligation,
            PerformanceObligation.id == RevenueSchedule.performance_obligation_id,
        )
        .join(ContractLine, ContractLine.id == PerformanceObligation.contract_line_id)
        .join(ContractVersion, ContractVersion.id == RevenueSchedule.contract_version_id)
        .join(Contract, Contract.id == ContractVersion.contract_id)
        .join(Customer, Customer.id == Contract.customer_id)
        .join(Product, Product.id == PerformanceObligation.product_id)
        .where(ScheduleLine.status != ScheduleLineStatus.SUPERSEDED)
    )
    statement = _contract_filters(statement, customer, contract)
    if product is not None:
        statement = statement.where(_product_filter(Product.product_code, Product.name, product))
    if status is not None:
        statement = statement.where(ScheduleLine.status == status)
    if period_from is not None:
        statement = statement.where(ScheduleLine.service_period >= period_from)
    if period_to is not None:
        statement = statement.where(ScheduleLine.service_period <= period_to)
    filtered = statement
    statement = apply_sort(
        statement,
        params.sort,
        {
            "contract_code": Contract.contract_code,
            "customer_name": Customer.name,
            "line_no": ContractLine.line_no,
            "product_code": Product.product_code,
            "service_period": ScheduleLine.service_period,
            "posting_period": ScheduleLine.posting_period,
            "amount": ScheduleLine.amount,
            "status": ScheduleLine.status,
        },
        [
            Contract.contract_code,
            ScheduleLine.service_period,
            ContractLine.line_no,
            ScheduleLine.id,
        ],
    )
    if params.format == "csv":
        return list_response(db, statement, params, RevenueScheduleRow, "revenue_schedule.csv")
    rows, total = page_of(db, statement, params)
    matching = filtered.subquery()
    total_amount = db.execute(select(func.coalesce(func.sum(matching.c.amount), 0))).scalar_one()
    return RevenueSchedulePage(
        items=[RevenueScheduleRow.model_validate(dict(row._mapping)) for row in rows],
        total=total,
        page=params.page,
        page_size=params.page_size,
        total_amount=Decimal(total_amount).quantize(CENT),
    )


# --------------------------------------------------------------------------- rollforward


_ROLLFORWARD_SORTS = ("period", "contract_code", "closing_deferred", "recognised", "billings")


def _rollforward_row(
    index: int,
    period: str,
    values: dict[str, int],
    contract: tuple[int, str, str] | None = None,
) -> RollforwardRow:
    contract_id, code, customer = contract if contract else (None, None, None)
    return RollforwardRow(
        id=index,
        period=period,
        contract_id=contract_id,
        contract_code=code,
        customer_name=customer,
        **{name: from_cents(amount) for name, amount in values.items()},
    )


_FLOWS = (
    "billings",
    "billed_to_unbilled",
    "credit_notes",
    "adjustments",
    "recognised_from_deferred",
    "recognised",
)


def _totals_by_period(balances: dict[int, list[PeriodBalance]]) -> dict[str, dict[str, int]]:
    """Add every contract up month by month. A month a contract is idle changes nothing, so its
    balance carries forward by adding only the changes."""
    flows: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for rows in balances.values():
        for row in rows:
            for name in _FLOWS:
                flows[row.period][name] += getattr(row, name)
            flows[row.period]["deferred_change"] += row.closing_deferred - row.opening_deferred
            flows[row.period]["unbilled_change"] += row.closing_unbilled - row.opening_unbilled
    if not flows:
        return {}
    result: dict[str, dict[str, int]] = {}
    deferred = unbilled = 0
    for period in iter_periods(min(flows), max(flows)):
        month = flows.get(period, {})
        closing_deferred = deferred + month.get("deferred_change", 0)
        closing_unbilled = unbilled + month.get("unbilled_change", 0)
        result[period] = {
            **{name: month.get(name, 0) for name in _FLOWS},
            "opening_deferred": deferred,
            "closing_deferred": closing_deferred,
            "opening_unbilled": unbilled,
            "closing_unbilled": closing_unbilled,
        }
        deferred, unbilled = closing_deferred, closing_unbilled
    return result


def _in_range(period: str, first: str | None, last: str | None) -> bool:
    return (first is None or period >= first) and (last is None or period <= last)


def _by_contract(
    db: DbSession,
    balances: dict[int, list[PeriodBalance]],
    first: str,
    last: str,
) -> list[RollforwardRow]:
    """One row per contract and month in the range, for the drill-down from a monthly figure."""
    if not balances:
        return []
    names = {
        contract_id: (contract_id, code, customer)
        for contract_id, code, customer in db.execute(
            select(Contract.id, Contract.contract_code, Customer.name)
            .join(Customer, Customer.id == Contract.customer_id)
            .where(Contract.id.in_(list(balances)))
        ).tuples()
    }
    output: list[RollforwardRow] = []
    for contract_id in sorted(balances, key=lambda cid: names[cid][1]):
        rows = balances[contract_id]
        by_period = {row.period: row for row in rows}
        deferred = unbilled = 0
        for row in rows:
            if row.period < first:
                deferred, unbilled = row.closing_deferred, row.closing_unbilled
        for period in iter_periods(first, last):
            found = by_period.get(period)
            values = {
                **{name: getattr(found, name) if found else 0 for name in _FLOWS},
                "opening_deferred": found.opening_deferred if found else deferred,
                "closing_deferred": found.closing_deferred if found else deferred,
                "opening_unbilled": found.opening_unbilled if found else unbilled,
                "closing_unbilled": found.closing_unbilled if found else unbilled,
            }
            deferred, unbilled = values["closing_deferred"], values["closing_unbilled"]
            if any(values.values()):
                output.append(_rollforward_row(len(output) + 1, period, values, names[contract_id]))
    return output


@router.get(
    "/deferred-rollforward",
    response_model=Page[RollforwardRow],
    responses=CSV,
    dependencies=Accountant,
)
def deferred_rollforward(
    db: DbSession,
    params: Listing,
    period_from: PeriodFilter = None,
    period_to: PeriodFilter = None,
    customer: Search = None,
    contract: Search = None,
    product: Search = None,
    group_by: Annotated[str, Query(pattern="^(period|contract)$")] = "period",
) -> Any:
    """Plan §5.6, from the sub-ledger. `group_by=contract` needs a period range: it is the
    drill-down from one month's figures to the contracts behind them."""
    ids = _matching_contract_ids(db, customer, contract, product)
    balances = all_balances(db, ids)
    if group_by == "contract":
        if period_from is None or period_to is None:
            raise ApiError(
                422, "PERIOD_RANGE_REQUIRED", "By contract, give period_from and period_to."
            )
        rows = _by_contract(db, balances, period_from, period_to)
    else:
        rows = [
            _rollforward_row(index, period, values)
            for index, (period, values) in enumerate(_totals_by_period(balances).items(), start=1)
            if _in_range(period, period_from, period_to)
        ]
    return _rows_response(
        _sorted_rows(rows, params.sort, _ROLLFORWARD_SORTS),
        params,
        RollforwardRow,
        "deferred_rollforward.csv",
    )


@router.get(
    "/recognized-vs-deferred",
    response_model=Page[RecognizedVsDeferredRow],
    responses=CSV,
    dependencies=Accountant,
)
def recognized_vs_deferred(
    db: DbSession,
    params: Listing,
    period_from: PeriodFilter = None,
    period_to: PeriodFilter = None,
    customer: Search = None,
    contract: Search = None,
    product: Search = None,
) -> Any:
    """Monthly recognised revenue and the balances at each month end (plan §9 Trend)."""
    ids = _matching_contract_ids(db, customer, contract, product)
    totals = _totals_by_period(all_balances(db, ids))
    rows = [
        RecognizedVsDeferredRow(
            id=index,
            period=period,
            recognised=from_cents(values["recognised"]),
            deferred=from_cents(values["closing_deferred"]),
            unbilled=from_cents(values["closing_unbilled"]),
        )
        for index, (period, values) in enumerate(totals.items(), start=1)
        if _in_range(period, period_from, period_to)
    ]
    return _rows_response(
        _sorted_rows(rows, params.sort, ("period", "recognised", "deferred", "unbilled")),
        params,
        RecognizedVsDeferredRow,
        "recognized_vs_deferred.csv",
    )


# --------------------------------------------------------------------------- journals and GL


@router.get(
    "/journal-register",
    response_model=Page[JournalRegisterRow],
    responses=CSV,
    dependencies=Accountant,
)
def journal_register(
    db: DbSession,
    params: Listing,
    period_from: PeriodFilter = None,
    period_to: PeriodFilter = None,
    customer: Search = None,
    contract: Search = None,
    product: Search = None,
    account: Search = None,
    status: BatchStatus | None = None,
    entry_type: JournalEntryType | None = None,
) -> Any:
    """All journal lines by period, status and account (plan §9)."""
    statement = journal_lines_query().join(Customer, Customer.id == Contract.customer_id)
    statement = statement.add_columns(Customer.name.label("customer_name"))
    statement = _contract_filters(statement, customer, contract)
    if product is not None:
        statement = statement.where(_product_filter(Product.product_code, Product.name, product))
    if account is not None:
        statement = statement.where(
            or_(
                _text_filter(GlAccount.account_code, account), _text_filter(GlAccount.name, account)
            )
        )
    if status is not None:
        statement = statement.where(JournalBatch.status == status)
    if entry_type is not None:
        statement = statement.where(JournalEntry.entry_type == entry_type)
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
            "entry_type": JournalEntry.entry_type,
            "contract_code": Contract.contract_code,
            "account_code": GlAccount.account_code,
            "debit": JournalLine.debit,
            "credit": JournalLine.credit,
        },
        [AccountingPeriod.period_key, JournalEntry.id, JournalLine.id],
    )
    return list_response(db, statement, params, JournalRegisterRow, "journal_register.csv")


@router.get(
    "/gl-summary", response_model=Page[GlSummaryRow], responses=CSV, dependencies=Accountant
)
def gl_summary(
    db: DbSession,
    params: Listing,
    period_from: PeriodFilter = None,
    period_to: PeriodFilter = None,
    customer: Search = None,
    contract: Search = None,
    product: Search = None,
    status: BatchStatus = BatchStatus.POSTED,
) -> Any:
    """Debit, credit and net per account per period. Posted batches unless asked otherwise."""
    debit = func.sum(JournalLine.debit)
    credit = func.sum(JournalLine.credit)
    default_order = (AccountingPeriod.period_key, GlAccount.account_code)
    statement = (
        select(
            func.row_number().over(order_by=default_order).label("id"),
            AccountingPeriod.period_key,
            GlAccount.account_code,
            GlAccount.name.label("account_name"),
            debit.label("debit"),
            credit.label("credit"),
            (debit - credit).label("net"),
        )
        .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
        .join(JournalBatch, JournalBatch.id == JournalEntry.batch_id)
        .join(AccountingPeriod, AccountingPeriod.id == JournalBatch.period_id)
        .join(GlAccount, GlAccount.id == JournalLine.account_id)
        .join(Contract, Contract.id == JournalEntry.contract_id)
        .join(Customer, Customer.id == Contract.customer_id)
        .outerjoin(Product, Product.id == JournalLine.product_id)
        .where(JournalBatch.status == status)
        .group_by(AccountingPeriod.period_key, GlAccount.account_code, GlAccount.name)
    )
    statement = _contract_filters(statement, customer, contract)
    if product is not None:
        statement = statement.where(_product_filter(Product.product_code, Product.name, product))
    if period_from is not None:
        statement = statement.where(AccountingPeriod.period_key >= period_from)
    if period_to is not None:
        statement = statement.where(AccountingPeriod.period_key <= period_to)
    statement = apply_sort(
        statement,
        params.sort,
        {
            "period_key": AccountingPeriod.period_key,
            "account_code": GlAccount.account_code,
            "debit": debit,
            "credit": credit,
            "net": debit - credit,
        },
        list(default_order),
    )
    return list_response(db, statement, params, GlSummaryRow, "gl_summary.csv")


# --------------------------------------------------------------------------- MRR / ARR


@router.get("/mrr-arr", response_model=Page[MrrArrRow], responses=CSV, dependencies=Accountant)
def mrr_arr(
    db: DbSession,
    params: Listing,
    period_from: PeriodFilter = None,
    period_to: PeriodFilter = None,
    customer: Search = None,
    contract: Search = None,
    product: Search = None,
) -> Any:
    """Plan §5.9. Non-GAAP: always shown apart from recognised revenue."""
    cancellation = aliased(ContractVersion)
    statement = (
        select(
            ContractLine.net_price,
            ContractLine.service_start,
            ContractLine.service_end,
            cancellation.effective_date.label("stopped_on"),
        )
        .join(Product, Product.id == ContractLine.product_id)
        .join(ContractVersion, ContractVersion.id == ContractLine.contract_version_id)
        .join(Contract, Contract.id == ContractVersion.contract_id)
        .join(Customer, Customer.id == Contract.customer_id)
        .outerjoin(
            cancellation,
            (cancellation.contract_id == Contract.id)
            & (cancellation.event_type == ContractEventType.CANCELLATION),
        )
        .where(
            Product.recognition_method.in_(
                [RecognitionMethod.RATABLE_DAILY, RecognitionMethod.RATABLE_MONTHLY]
            )
        )
    )
    statement = _contract_filters(statement, customer, contract)
    if product is not None:
        statement = statement.where(_product_filter(Product.product_code, Product.name, product))
    lines = [
        MrrLine(to_cents(net), start, end, stopped)
        for net, start, end, stopped in db.execute(statement).tuples()
    ]
    if not lines:
        return _rows_response([], params, MrrArrRow, "mrr_arr.csv")
    first = period_from or min(period_key(line.service_start) for line in lines)
    last = period_to or max(period_key(line.service_end) for line in lines)
    rows = [
        MrrArrRow(id=index, period=period, mrr=from_cents(cents), arr=from_cents(cents * 12))
        for index, (period, cents) in enumerate(mrr_by_period(lines, first, last).items(), start=1)
    ]
    return _rows_response(
        _sorted_rows(rows, params.sort, ("period", "mrr", "arr")), params, MrrArrRow, "mrr_arr.csv"
    )


# --------------------------------------------------------------------------- close status


@router.get("/close-status", response_model=CloseStatusPage, responses=CSV, dependencies=Accountant)
def close_status(
    db: DbSession,
    params: Listing,
    period_from: PeriodFilter = None,
    period_to: PeriodFilter = None,
) -> Any:
    """State of each period; the checklist of the current one is computed live (§5.8)."""
    closer = aliased(User)
    batch_count = (
        select(func.count(JournalBatch.id))
        .where(JournalBatch.period_id == AccountingPeriod.id)
        .scalar_subquery()
    )
    posted_count = (
        select(func.count(JournalBatch.id))
        .where(
            JournalBatch.period_id == AccountingPeriod.id,
            JournalBatch.status == BatchStatus.POSTED,
        )
        .scalar_subquery()
    )
    statement = select(
        AccountingPeriod.id,
        AccountingPeriod.period_key,
        AccountingPeriod.status,
        closer.full_name.label("closed_by_name"),
        AccountingPeriod.closed_at,
        batch_count.label("batches"),
        posted_count.label("posted_batches"),
    ).outerjoin(closer, closer.id == AccountingPeriod.closed_by)
    if period_from is not None:
        statement = statement.where(AccountingPeriod.period_key >= period_from)
    if period_to is not None:
        statement = statement.where(AccountingPeriod.period_key <= period_to)
    statement = apply_sort(
        statement,
        params.sort,
        {"period_key": AccountingPeriod.period_key, "status": AccountingPeriod.status},
        [AccountingPeriod.period_key],
    )
    if params.format == "csv":
        return list_response(db, statement, params, CloseStatusRow, "close_status.csv")
    rows, total = page_of(db, statement, params)
    current = db.scalar(
        select(AccountingPeriod.period_key).where(
            AccountingPeriod.status.in_([PeriodStatus.OPEN, PeriodStatus.CLOSING])
        )
    )
    return CloseStatusPage(
        items=[CloseStatusRow.model_validate(dict(row._mapping)) for row in rows],
        total=total,
        page=params.page,
        page_size=params.page_size,
        current=checklist_out(db, current) if current else None,
    )


# --------------------------------------------------------------------------- validation log


@router.get(
    "/validation-log", response_model=Page[ValidationLogRow], responses=CSV, dependencies=Uploader
)
def validation_log(
    db: DbSession,
    params: Listing,
    period_from: PeriodFilter = None,
    period_to: PeriodFilter = None,
    code: Annotated[str | None, Query(pattern=r"^E\d{3}$")] = None,
) -> Any:
    """Every validation error of every upload (plan §7.1)."""
    statement = select(
        ValidationError.id,
        UploadFile.id.label("upload_id"),
        UploadFile.original_filename.label("filename"),
        UploadFile.period_key,
        ValidationError.row_number,
        ValidationError.column_name,
        ValidationError.error_code,
        ValidationError.message,
        ValidationError.raw_value,
    ).join(UploadFile, UploadFile.id == ValidationError.upload_file_id)
    if code is not None:
        statement = statement.where(ValidationError.error_code == code)
    if period_from is not None:
        statement = statement.where(UploadFile.period_key >= period_from)
    if period_to is not None:
        statement = statement.where(UploadFile.period_key <= period_to)
    statement = apply_sort(
        statement,
        params.sort,
        {
            "filename": UploadFile.original_filename,
            "period_key": UploadFile.period_key,
            "row_number": ValidationError.row_number,
            "error_code": ValidationError.error_code,
        },
        [UploadFile.period_key, UploadFile.id, ValidationError.row_number, ValidationError.id],
    )
    return list_response(db, statement, params, ValidationLogRow, "validation_log.csv")
