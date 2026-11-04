"""Response bodies for /contracts and engine runs (plan §8). Money is a string in JSON (D1)."""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel

from app.models.enums import (
    ContractEventType,
    ContractStatus,
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


class JobAccepted(BaseModel):
    job_id: int
