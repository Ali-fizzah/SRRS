"""Response bodies for /contracts and engine runs (plan §8). Money is a string in JSON (D1)."""

from datetime import date
from decimal import Decimal
from typing import Any

from pydantic import BaseModel

from app.models.enums import (
    ContractEventType,
    ContractStatus,
    ObligationStatus,
    PeriodStatus,
    RecognitionMethod,
    ScheduleLineStatus,
)


class ContractOut(BaseModel):
    """A contract with the fields of its current version."""

    id: int
    contract_code: str
    customer_code: str
    customer_name: str
    status: ContractStatus
    current_version_no: int
    event_type: ContractEventType
    effective_date: date
    start_date: date
    end_date: date
    transaction_price: Decimal
    booked_period: str
    has_schedule: bool


class VersionSummaryOut(BaseModel):
    version_no: int
    event_type: ContractEventType
    effective_date: date
    start_date: date
    end_date: date
    transaction_price: Decimal
    booked_period: str


class ContractDetailOut(ContractOut):
    versions: list[VersionSummaryOut]


class ContractLineOut(BaseModel):
    id: int
    line_no: int
    product_code: str
    product_name: str
    is_separate_obligation: bool
    quantity: Decimal
    unit_price: Decimal
    discount: Decimal
    net_price: Decimal
    service_start: date
    service_end: date
    completion_date: date | None


class DeliveryOut(BaseModel):
    delivery_code: str
    line_no: int
    delivery_date: date
    units_fraction: Decimal


class ObligationOut(BaseModel):
    id: int
    line_no: int
    product_code: str
    method: RecognitionMethod
    ssp_amount: Decimal
    allocated_amount: Decimal
    service_start: date
    service_end: date
    completion_date: date | None
    status: ObligationStatus


class VersionDetailOut(VersionSummaryOut):
    lines: list[ContractLineOut]
    obligations: list[ObligationOut]
    deliveries: list[DeliveryOut]


class InvoiceOut(BaseModel):
    invoice_number: str
    invoice_date: date
    total_amount: Decimal


class CreditNoteOut(BaseModel):
    credit_note_number: str
    invoice_number: str
    credit_date: date
    amount: Decimal
    reason: str


class PeriodBalanceOut(BaseModel):
    """Plan §5.6: opening + billings - credit notes - recognised (from deferred) = closing."""

    period: str
    opening_deferred: Decimal
    opening_unbilled: Decimal
    billings: Decimal
    credit_notes: Decimal
    recognised: Decimal
    recognised_from_deferred: Decimal
    closing_deferred: Decimal
    closing_unbilled: Decimal


class ContractBillingOut(BaseModel):
    invoices: list[InvoiceOut]
    credit_notes: list[CreditNoteOut]
    balances: list[PeriodBalanceOut]
    deferred: Decimal
    unbilled: Decimal


class SourceRowOut(BaseModel):
    """A row as it was uploaded (CLAUDE.md rule 5), the end point of the drill-down (§9)."""

    id: int
    record_type: str
    upload_id: int
    filename: str
    source_row: int | None
    payload: dict[str, Any] | None


class ScheduleLineOut(BaseModel):
    id: int
    version_no: int
    line_no: int
    product_code: str
    method: RecognitionMethod
    service_period: str
    amount: Decimal
    status: ScheduleLineStatus
    posting_period: str | None
    is_catch_up: bool


class SchedulePage(BaseModel):
    items: list[ScheduleLineOut]
    total: int
    page: int
    page_size: int
    total_amount: Decimal  # every matching line, not just this page; superseded lines excluded


class PeriodOut(BaseModel):
    id: int
    period_key: str
    start_date: date
    end_date: date
    status: PeriodStatus


class JobAccepted(BaseModel):
    job_id: int
