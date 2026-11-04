"""Contracts and their drill-down tabs (plan §8 Contracts: UPLOADER)."""

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import Select, exists, func, or_, select
from sqlalchemy.orm import aliased

from app.api.errors import ApiError
from app.api.listing import (
    Listing,
    Page,
    PeriodFilter,
    Search,
    apply_sort,
    list_response,
    page_of,
)
from app.api.v1.stubs import stub
from app.auth.deps import DbSession, require_role
from app.auth.roles import Role
from app.models import (
    Contract,
    ContractLine,
    ContractVersion,
    Customer,
    PerformanceObligation,
    Product,
    RevenueSchedule,
    ScheduleLine,
)
from app.models.enums import ScheduleLineStatus
from app.schemas.contracts import ContractOut, ScheduleLineOut, SchedulePage

router = APIRouter(prefix="/contracts", tags=["contracts"])

CanRead = [Depends(require_role(Role.UPLOADER))]
CSV: dict[int | str, dict[str, Any]] = {200: {"content": {"text/csv": {}}}}
CENT = Decimal("0.01")


def _contracts() -> Select[Any]:
    """Contracts with the fields of their current version (ContractOut)."""
    has_schedule = exists().where(PerformanceObligation.contract_version_id == ContractVersion.id)
    return (
        select(
            Contract.id,
            Contract.contract_code,
            Customer.customer_code,
            Customer.name.label("customer_name"),
            Contract.status,
            Contract.current_version_no,
            ContractVersion.event_type,
            ContractVersion.effective_date,
            ContractVersion.start_date,
            ContractVersion.end_date,
            ContractVersion.transaction_price,
            ContractVersion.booked_period,
            has_schedule.label("has_schedule"),
        )
        .join(Customer, Customer.id == Contract.customer_id)
        .join(
            ContractVersion,
            (ContractVersion.contract_id == Contract.id)
            & (ContractVersion.version_no == Contract.current_version_no),
        )
    )


@router.get("", response_model=Page[ContractOut], responses=CSV, dependencies=CanRead)
def list_contracts(
    db: DbSession,
    params: Listing,
    customer: Search = None,
    contract: Search = None,
    product: Search = None,
    period_from: PeriodFilter = None,
    period_to: PeriodFilter = None,
) -> Any:
    """The period filters use the current version's booked period."""
    statement = _contracts()
    if customer is not None:
        statement = statement.where(
            or_(
                Customer.customer_code.icontains(customer, autoescape=True),
                Customer.name.icontains(customer, autoescape=True),
            )
        )
    if contract is not None:
        statement = statement.where(Contract.contract_code.icontains(contract, autoescape=True))
    if product is not None:
        # A line of any version counts: an upgrade's version holds only the added lines.
        any_version = aliased(ContractVersion)
        statement = statement.where(
            exists()
            .where(any_version.contract_id == Contract.id)
            .where(ContractLine.contract_version_id == any_version.id)
            .where(Product.id == ContractLine.product_id)
            .where(
                or_(
                    Product.product_code.icontains(product, autoescape=True),
                    Product.name.icontains(product, autoescape=True),
                )
            )
        )
    if period_from is not None:
        statement = statement.where(ContractVersion.booked_period >= period_from)
    if period_to is not None:
        statement = statement.where(ContractVersion.booked_period <= period_to)
    statement = apply_sort(
        statement,
        params.sort,
        {
            "contract_code": Contract.contract_code,
            "customer_code": Customer.customer_code,
            "customer_name": Customer.name,
            "status": Contract.status,
            "current_version_no": Contract.current_version_no,
            "event_type": ContractVersion.event_type,
            "effective_date": ContractVersion.effective_date,
            "start_date": ContractVersion.start_date,
            "end_date": ContractVersion.end_date,
            "transaction_price": ContractVersion.transaction_price,
            "booked_period": ContractVersion.booked_period,
        },
        [Contract.contract_code],
    )
    return list_response(db, statement, params, ContractOut, "contracts.csv")


@router.get("/{contract_id}", response_model=ContractOut, dependencies=CanRead)
def get_contract(contract_id: int, db: DbSession) -> ContractOut:
    """One contract with its current version; versions, lines and POs arrive in task P3-T6."""
    row = db.execute(_contracts().where(Contract.id == contract_id)).first()
    if row is None:
        raise ApiError(404, "NOT_FOUND", f"Contract {contract_id} does not exist.")
    return ContractOut.model_validate(dict(row._mapping))


@router.get(
    "/{contract_id}/schedule",
    response_model=SchedulePage,
    responses=CSV,
    dependencies=CanRead,
)
def get_contract_schedule(
    contract_id: int,
    db: DbSession,
    params: Listing,
    period_from: PeriodFilter = None,
    period_to: PeriodFilter = None,
) -> Any:
    """Schedule lines of every version. The period filters use the service period."""
    if db.get(Contract, contract_id) is None:
        raise ApiError(404, "NOT_FOUND", f"Contract {contract_id} does not exist.")
    statement = (
        select(
            ScheduleLine.id,
            ContractVersion.version_no,
            ContractLine.line_no,
            Product.product_code,
            PerformanceObligation.method,
            ScheduleLine.service_period,
            ScheduleLine.amount,
            ScheduleLine.status,
            ScheduleLine.posting_period,
            ScheduleLine.is_catch_up,
        )
        .join(RevenueSchedule, RevenueSchedule.id == ScheduleLine.schedule_id)
        .join(ContractVersion, ContractVersion.id == RevenueSchedule.contract_version_id)
        .join(
            PerformanceObligation,
            PerformanceObligation.id == RevenueSchedule.performance_obligation_id,
        )
        .join(ContractLine, ContractLine.id == PerformanceObligation.contract_line_id)
        .join(Product, Product.id == PerformanceObligation.product_id)
        .where(ContractVersion.contract_id == contract_id)
    )
    if period_from is not None:
        statement = statement.where(ScheduleLine.service_period >= period_from)
    if period_to is not None:
        statement = statement.where(ScheduleLine.service_period <= period_to)

    filtered = statement
    statement = apply_sort(
        statement,
        params.sort,
        {
            "version_no": ContractVersion.version_no,
            "line_no": ContractLine.line_no,
            "product_code": Product.product_code,
            "service_period": ScheduleLine.service_period,
            "amount": ScheduleLine.amount,
            "status": ScheduleLine.status,
            "posting_period": ScheduleLine.posting_period,
        },
        [ContractVersion.version_no, ContractLine.line_no, ScheduleLine.service_period],
    )
    if params.format == "csv":
        return list_response(
            db, statement, params, ScheduleLineOut, f"contract_{contract_id}_schedule.csv"
        )

    rows, total = page_of(db, statement, params)
    matching = filtered.subquery()  # §4: aggregations are computed in SQL, over every page
    total_amount = db.execute(
        select(func.coalesce(func.sum(matching.c.amount), 0)).where(
            matching.c.status != ScheduleLineStatus.SUPERSEDED
        )
    ).scalar_one()
    return SchedulePage(
        items=[ScheduleLineOut.model_validate(dict(row._mapping)) for row in rows],
        total=total,
        page=params.page,
        page_size=params.page_size,
        total_amount=Decimal(total_amount).quantize(CENT),
    )


stub(router, "GET", "/{contract_id}/versions/{version_no}", Role.UPLOADER, "P3-T6")
stub(router, "GET", "/{contract_id}/billing", Role.UPLOADER, "P3-T6")
stub(router, "GET", "/{contract_id}/journal-lines", Role.UPLOADER, "P4-T4")
stub(router, "GET", "/{contract_id}/source-rows", Role.UPLOADER, "P3-T6")
