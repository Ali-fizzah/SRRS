"""Response and request bodies for journals (plan §8). Money is a string in JSON (D1)."""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.models.enums import BatchStatus, JournalEntryType


class JournalBatchOut(BaseModel):
    id: int
    period_key: str
    batch_no: int
    status: BatchStatus
    generated_by_name: str
    generated_by_id: int
    approved_by_name: str | None
    approved_at: datetime | None
    posted_by_name: str | None
    posted_at: datetime | None
    total_debit: Decimal
    total_credit: Decimal
    entry_count: int


class JournalLineOut(BaseModel):
    """One journal line with its entry, for the batch page and the contract's Journals tab."""

    id: int
    entry_id: int
    entry_type: JournalEntryType
    entry_date: date
    description: str | None
    contract_id: int
    contract_code: str
    version_no: int
    source_type: str
    source_id: int | None
    source_upload_id: int | None
    source_row: int | None
    reverses_entry_id: int | None
    account_code: str
    account_name: str
    debit: Decimal
    credit: Decimal
    product_code: str | None
    line_no: int | None
    batch_id: int
    batch_no: int
    batch_status: BatchStatus
    period_key: str
    first_of_entry: bool
    can_reverse: bool


class JournalBatchDetail(BaseModel):
    """A batch and one page of its lines (plan §4: paging happens on the server)."""

    batch: JournalBatchOut
    balanced: bool
    items: list[JournalLineOut]
    total: int
    page: int
    page_size: int


class SendBackIn(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)


class ReverseIn(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)


class ReverseOut(BaseModel):
    batch_id: int
