"""Enumerations stored as PostgreSQL ENUM types (plan §6.1)."""

from enum import StrEnum


class RecognitionMethod(StrEnum):
    RATABLE_DAILY = "RATABLE_DAILY"
    RATABLE_MONTHLY = "RATABLE_MONTHLY"
    POINT_IN_TIME = "POINT_IN_TIME"


class SspSource(StrEnum):
    FIXED = "FIXED"
    LIST_PRICE = "LIST_PRICE"
    PCT_OF_LIST = "PCT_OF_LIST"


class GlAccountType(StrEnum):
    ASSET = "ASSET"
    LIABILITY = "LIABILITY"
    REVENUE = "REVENUE"


class AccountRole(StrEnum):
    """D12: roles that GL mappings resolve to accounts."""

    AR = "AR"
    UNBILLED_AR = "UNBILLED_AR"
    DEFERRED_REVENUE = "DEFERRED_REVENUE"
    REVENUE = "REVENUE"


class ContractStatus(StrEnum):
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class ContractEventType(StrEnum):
    NEW = "NEW"
    RENEWAL = "RENEWAL"
    CANCELLATION = "CANCELLATION"
    UPGRADE = "UPGRADE"


class ObligationStatus(StrEnum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    SATISFIED = "SATISFIED"


class ScheduleStatus(StrEnum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class ScheduleLineStatus(StrEnum):
    PENDING = "PENDING"
    POSTED = "POSTED"
    SUPERSEDED = "SUPERSEDED"


class PeriodStatus(StrEnum):
    OPEN = "OPEN"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"


class BatchStatus(StrEnum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    POSTED = "POSTED"


class JournalEntryType(StrEnum):
    INVOICE = "INVOICE"
    CREDIT_NOTE = "CREDIT_NOTE"
    REVENUE = "REVENUE"
    REVENUE_CATCH_UP = "REVENUE_CATCH_UP"
    REVERSAL = "REVERSAL"
    ADJUSTMENT = "ADJUSTMENT"


class UploadTemplate(StrEnum):
    """The seven input templates (plan §7), in dependency order."""

    CUSTOMERS = "customers"
    PRODUCTS = "products"
    CONTRACTS = "contracts"
    CONTRACT_LINES = "contract_lines"
    INVOICES = "invoices"
    CREDIT_NOTES = "credit_notes"
    DELIVERIES = "deliveries"


class UploadStatus(StrEnum):
    RECEIVED = "RECEIVED"
    VALIDATING = "VALIDATING"
    ACCEPTED = "ACCEPTED"
    PARTIAL = "PARTIAL"
    REJECTED = "REJECTED"


class JobType(StrEnum):
    INGEST = "INGEST"
    RECOGNITION = "RECOGNITION"
    JOURNALS = "JOURNALS"
    EXPORT = "EXPORT"


class JobStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    DONE = "DONE"
    FAILED = "FAILED"
