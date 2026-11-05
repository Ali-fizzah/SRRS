"""Response bodies for reports and the close workflow (plan §8). Money is a string in JSON (D1)."""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from app.models.enums import (
    BatchStatus,
    JournalEntryType,
    PeriodStatus,
    RecognitionMethod,
    ScheduleLineStatus,
)


class ChecklistItemOut(BaseModel):
    id: str
    label: str
    status: Literal["pass", "warn", "fail"]
    detail: str


class ChecklistOut(BaseModel):
    period_key: str
    status: PeriodStatus
    can_close: bool
    items: list[ChecklistItemOut]


class ReopenIn(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)


class RevenueScheduleRow(BaseModel):
    id: int
    contract_id: int
    contract_code: str
    customer_name: str
    version_no: int
    line_no: int
    product_code: str
    method: RecognitionMethod
    service_period: str
    posting_period: str | None
    is_catch_up: bool
    amount: Decimal
    status: ScheduleLineStatus


class RevenueSchedulePage(BaseModel):
    items: list[RevenueScheduleRow]
    total: int
    page: int
    page_size: int
    total_amount: Decimal


class RollforwardRow(BaseModel):
    """§5.6: opening + billings - credit notes + reversals - cleared - recognised = closing."""

    id: int
    period: str
    contract_id: int | None = None
    contract_code: str | None = None
    customer_name: str | None = None
    opening_deferred: Decimal
    billings: Decimal
    billed_to_unbilled: Decimal
    credit_notes: Decimal
    adjustments: Decimal
    recognised_from_deferred: Decimal
    closing_deferred: Decimal
    opening_unbilled: Decimal
    closing_unbilled: Decimal
    recognised: Decimal


class RecognizedVsDeferredRow(BaseModel):
    id: int
    period: str
    recognised: Decimal
    deferred: Decimal
    unbilled: Decimal


class JournalRegisterRow(BaseModel):
    id: int
    period_key: str
    batch_id: int
    batch_no: int
    batch_status: BatchStatus
    entry_id: int
    entry_type: JournalEntryType
    entry_date: date
    contract_id: int
    contract_code: str
    customer_name: str
    account_code: str
    account_name: str
    debit: Decimal
    credit: Decimal
    product_code: str | None
    description: str | None


class GlSummaryRow(BaseModel):
    id: int
    period_key: str
    account_code: str
    account_name: str
    debit: Decimal
    credit: Decimal
    net: Decimal  # debit minus credit


class MrrArrRow(BaseModel):
    id: int
    period: str
    mrr: Decimal
    arr: Decimal


class CloseStatusRow(BaseModel):
    id: int
    period_key: str
    status: PeriodStatus
    closed_by_name: str | None
    closed_at: datetime | None
    batches: int
    posted_batches: int


class CloseStatusPage(BaseModel):
    items: list[CloseStatusRow]
    total: int
    page: int
    page_size: int
    current: ChecklistOut | None


class ValidationLogRow(BaseModel):
    id: int
    upload_id: int
    filename: str
    period_key: str
    row_number: int
    column_name: str | None
    error_code: str
    message: str
    raw_value: str | None
