"""SQLAlchemy 2.0 typed models (plan §6). Importing this package registers every table."""

from app.models.billing import CreditNote, Invoice, InvoiceLine
from app.models.contracts import (
    Contract,
    ContractLine,
    ContractVersion,
    Delivery,
    PerformanceObligation,
)
from app.models.control import (
    AuditLog,
    JobRun,
    Role,
    UploadFile,
    User,
    UserRole,
    ValidationError,
)
from app.models.ledger import AccountingPeriod, JournalBatch, JournalEntry, JournalLine
from app.models.master import Customer, GlAccount, GlMapping, Product, SspRule
from app.models.revenue import RevenueSchedule, ScheduleLine

__all__ = [
    "AccountingPeriod",
    "AuditLog",
    "Contract",
    "ContractLine",
    "ContractVersion",
    "CreditNote",
    "Customer",
    "Delivery",
    "GlAccount",
    "GlMapping",
    "Invoice",
    "InvoiceLine",
    "JobRun",
    "JournalBatch",
    "JournalEntry",
    "JournalLine",
    "PerformanceObligation",
    "Product",
    "Role",
    "RevenueSchedule",
    "ScheduleLine",
    "SspRule",
    "UploadFile",
    "User",
    "UserRole",
    "ValidationError",
]
