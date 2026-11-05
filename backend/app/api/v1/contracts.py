"""Contracts and their drill-down tabs (plan §8 Contracts: UPLOADER)."""

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import Select, exists, func, literal, or_, select, union_all
from sqlalchemy.orm import Session, aliased

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
from app.engine.money import from_cents
from app.models import (
    Contract,
    ContractLine,
    ContractVersion,
    CreditNote,
    Customer,
    Delivery,
    Invoice,
    InvoiceLine,
    PerformanceObligation,
    Product,
    RevenueSchedule,
    ScheduleLine,
    UploadFile,
)
from app.models.enums import ScheduleLineStatus
from app.schemas.contracts import (
    ContractBillingOut,
    ContractDetailOut,
    ContractLineOut,
    ContractOut,
    CreditNoteOut,
    DeliveryOut,
    InvoiceOut,
    ObligationOut,
    PeriodBalanceOut,
    ScheduleLineOut,
    SchedulePage,
    SourceRowOut,
    VersionDetailOut,
    VersionSummaryOut,
)
from app.services.billing import contract_balances

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


_VERSION_COLUMNS = (
    ContractVersion.version_no,
    ContractVersion.event_type,
    ContractVersion.effective_date,
    ContractVersion.start_date,
    ContractVersion.end_date,
    ContractVersion.transaction_price,
    ContractVersion.booked_period,
)


def _require_contract(db: Session, contract_id: int) -> None:
    if db.get(Contract, contract_id) is None:
        raise ApiError(404, "NOT_FOUND", f"Contract {contract_id} does not exist.")


@router.get("/{contract_id}", response_model=ContractDetailOut, dependencies=CanRead)
def get_contract(contract_id: int, db: DbSession) -> ContractDetailOut:
    """One contract: its current version and the list of all its versions (§5.5)."""
    row = db.execute(_contracts().where(Contract.id == contract_id)).first()
    if row is None:
        raise ApiError(404, "NOT_FOUND", f"Contract {contract_id} does not exist.")
    versions = db.execute(
        select(*_VERSION_COLUMNS)
        .where(ContractVersion.contract_id == contract_id)
        .order_by(ContractVersion.version_no)
    ).all()
    return ContractDetailOut(
        **dict(row._mapping),
        versions=[VersionSummaryOut.model_validate(dict(v._mapping)) for v in versions],
    )


@router.get(
    "/{contract_id}/versions/{version_no}",
    response_model=VersionDetailOut,
    dependencies=CanRead,
)
def get_contract_version(contract_id: int, version_no: int, db: DbSession) -> VersionDetailOut:
    """One version with its lines, obligations + allocation, and deliveries."""
    row = db.execute(
        select(ContractVersion.id, *_VERSION_COLUMNS).where(
            ContractVersion.contract_id == contract_id, ContractVersion.version_no == version_no
        )
    ).first()
    if row is None:
        raise ApiError(404, "NOT_FOUND", f"Contract {contract_id} has no version {version_no}.")
    lines = db.execute(
        select(
            ContractLine.id,
            ContractLine.line_no,
            Product.product_code,
            Product.name.label("product_name"),
            Product.is_separate_obligation,
            ContractLine.quantity,
            ContractLine.unit_price,
            ContractLine.discount,
            ContractLine.net_price,
            ContractLine.service_start,
            ContractLine.service_end,
            ContractLine.completion_date,
        )
        .join(Product, Product.id == ContractLine.product_id)
        .where(ContractLine.contract_version_id == row.id)
        .order_by(ContractLine.line_no)
    ).all()
    obligations = db.execute(
        select(
            PerformanceObligation.id,
            ContractLine.line_no,
            Product.product_code,
            PerformanceObligation.method,
            PerformanceObligation.ssp_amount,
            PerformanceObligation.allocated_amount,
            PerformanceObligation.service_start,
            PerformanceObligation.service_end,
            PerformanceObligation.completion_date,
            PerformanceObligation.status,
        )
        .join(ContractLine, ContractLine.id == PerformanceObligation.contract_line_id)
        .join(Product, Product.id == PerformanceObligation.product_id)
        .where(PerformanceObligation.contract_version_id == row.id)
        .order_by(ContractLine.line_no)
    ).all()
    deliveries = db.execute(
        select(
            Delivery.delivery_code,
            ContractLine.line_no,
            Delivery.delivery_date,
            Delivery.units_fraction,
        )
        .join(ContractLine, ContractLine.id == Delivery.contract_line_id)
        .where(ContractLine.contract_version_id == row.id)
        .order_by(Delivery.delivery_date, Delivery.id)
    ).all()
    summary = {key: value for key, value in row._mapping.items() if key != "id"}
    return VersionDetailOut(
        **summary,
        lines=[ContractLineOut.model_validate(dict(r._mapping)) for r in lines],
        obligations=[ObligationOut.model_validate(dict(r._mapping)) for r in obligations],
        deliveries=[DeliveryOut.model_validate(dict(r._mapping)) for r in deliveries],
    )


@router.get("/{contract_id}/billing", response_model=ContractBillingOut, dependencies=CanRead)
def get_contract_billing(contract_id: int, db: DbSession) -> ContractBillingOut:
    """Invoices, credit notes and the deferred / unbilled rollforward (plan §5.6)."""
    _require_contract(db, contract_id)
    invoices = db.execute(
        select(Invoice.invoice_number, Invoice.invoice_date, Invoice.total_amount)
        .where(Invoice.contract_id == contract_id)
        .order_by(Invoice.invoice_date, Invoice.invoice_number)
    ).all()
    credit_notes = db.execute(
        select(
            CreditNote.credit_note_number,
            Invoice.invoice_number,
            CreditNote.credit_date,
            CreditNote.amount,
            CreditNote.reason,
        )
        .join(Invoice, Invoice.id == CreditNote.invoice_id)
        .where(Invoice.contract_id == contract_id)
        .order_by(CreditNote.credit_date, CreditNote.credit_note_number)
    ).all()
    rows = contract_balances(db, contract_id)
    last = rows[-1] if rows else None
    return ContractBillingOut(
        invoices=[InvoiceOut.model_validate(dict(r._mapping)) for r in invoices],
        credit_notes=[CreditNoteOut.model_validate(dict(r._mapping)) for r in credit_notes],
        balances=[
            PeriodBalanceOut(
                period=r.period,
                opening_deferred=from_cents(r.opening_deferred),
                opening_unbilled=from_cents(r.opening_unbilled),
                billings=from_cents(r.billings),
                credit_notes=from_cents(r.credit_notes),
                recognised=from_cents(r.recognised),
                recognised_from_deferred=from_cents(r.recognised_from_deferred),
                closing_deferred=from_cents(r.closing_deferred),
                closing_unbilled=from_cents(r.closing_unbilled),
            )
            for r in rows
        ],
        deferred=from_cents(last.closing_deferred if last else 0),
        unbilled=from_cents(last.closing_unbilled if last else 0),
    )


@router.get(
    "/{contract_id}/source-rows",
    response_model=Page[SourceRowOut],
    responses=CSV,
    dependencies=CanRead,
)
def list_source_rows(contract_id: int, db: DbSession, params: Listing) -> Any:
    """Every uploaded row behind this contract, as it was in the file (CLAUDE.md rule 5)."""
    _require_contract(db, contract_id)

    def rows(record_type: str, model: Any) -> Select[Any]:
        return select(
            literal(record_type).label("record_type"),
            model.source_upload_id.label("upload_id"),
            model.source_row.label("source_row"),
            model.source_payload.label("payload"),
        ).where(model.source_upload_id.is_not(None))

    of_contract = ContractVersion.contract_id == contract_id
    unioned = union_all(
        rows("contract", ContractVersion).where(of_contract),
        rows("contract_line", ContractLine)
        .join(ContractVersion, ContractVersion.id == ContractLine.contract_version_id)
        .where(of_contract),
        rows("delivery", Delivery)
        .join(ContractLine, ContractLine.id == Delivery.contract_line_id)
        .join(ContractVersion, ContractVersion.id == ContractLine.contract_version_id)
        .where(of_contract),
        rows("invoice", Invoice).where(Invoice.contract_id == contract_id),
        rows("invoice_line", InvoiceLine)
        .join(Invoice, Invoice.id == InvoiceLine.invoice_id)
        .where(Invoice.contract_id == contract_id),
        rows("credit_note", CreditNote)
        .join(Invoice, Invoice.id == CreditNote.invoice_id)
        .where(Invoice.contract_id == contract_id),
    ).subquery("source")
    default_order = (unioned.c.upload_id, unioned.c.source_row, unioned.c.record_type)
    statement = select(
        func.row_number().over(order_by=default_order).label("id"),
        unioned.c.record_type,
        unioned.c.upload_id,
        UploadFile.original_filename.label("filename"),
        unioned.c.source_row,
        unioned.c.payload,
    ).join(UploadFile, UploadFile.id == unioned.c.upload_id)
    statement = apply_sort(
        statement,
        params.sort,
        {
            "record_type": unioned.c.record_type,
            "filename": UploadFile.original_filename,
            "source_row": unioned.c.source_row,
        },
        list(default_order),
    )
    return list_response(db, statement, params, SourceRowOut, f"contract_{contract_id}_source.csv")


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


stub(router, "GET", "/{contract_id}/journal-lines", Role.UPLOADER, "P4-T4")
