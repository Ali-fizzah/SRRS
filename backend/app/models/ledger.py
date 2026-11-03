"""Accounting periods, journal batches, entries and lines (plan §6.1, §5.7-5.8)."""

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Money, PeriodKey, fk, pg_enum
from app.models.enums import BatchStatus, JournalEntryType, PeriodStatus


class AccountingPeriod(Base):
    __tablename__ = "accounting_periods"

    period_key: Mapped[PeriodKey] = mapped_column(unique=True)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    status: Mapped[PeriodStatus] = mapped_column(
        pg_enum(PeriodStatus, "period_status"), server_default=PeriodStatus.OPEN.value
    )
    closed_by: Mapped[int | None] = fk("users.id", nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class JournalBatch(Base):
    __tablename__ = "journal_batches"
    __table_args__ = (UniqueConstraint("period_id", "batch_no"),)

    period_id: Mapped[int] = fk("accounting_periods.id")
    batch_no: Mapped[int] = mapped_column(Integer)
    status: Mapped[BatchStatus] = mapped_column(
        pg_enum(BatchStatus, "batch_status"), server_default=BatchStatus.DRAFT.value
    )
    generated_by: Mapped[int] = fk("users.id")
    approved_by: Mapped[int | None] = fk("users.id", nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    posted_by: Mapped[int | None] = fk("users.id", nullable=True)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    total_debit: Mapped[Money] = mapped_column(server_default=text("0"))
    total_credit: Mapped[Money] = mapped_column(server_default=text("0"))


class JournalEntry(Base):
    """Every entry carries contract, version, source document and source upload row (§5.7)."""

    __tablename__ = "journal_entries"

    batch_id: Mapped[int] = fk("journal_batches.id")
    entry_type: Mapped[JournalEntryType] = mapped_column(
        pg_enum(JournalEntryType, "journal_entry_type")
    )
    entry_date: Mapped[date] = mapped_column(Date)
    contract_id: Mapped[int] = fk("contracts.id")
    contract_version_id: Mapped[int] = fk("contract_versions.id")
    source_type: Mapped[str] = mapped_column(String(32))
    source_id: Mapped[int | None] = mapped_column(BigInteger)
    source_upload_id: Mapped[int | None] = fk("upload_files.id", nullable=True)
    source_row: Mapped[int | None] = mapped_column(Integer)
    reverses_entry_id: Mapped[int | None] = fk("journal_entries.id", nullable=True)
    description: Mapped[str | None] = mapped_column(Text)


class JournalLine(Base):
    __tablename__ = "journal_lines"
    __table_args__ = (
        CheckConstraint(
            "debit >= 0 AND credit >= 0 AND (debit = 0 OR credit = 0)", name="one_sided"
        ),
    )

    entry_id: Mapped[int] = fk("journal_entries.id")
    account_id: Mapped[int] = fk("gl_accounts.id")
    debit: Mapped[Money] = mapped_column(server_default=text("0"))
    credit: Mapped[Money] = mapped_column(server_default=text("0"))
    product_id: Mapped[int | None] = fk("products.id", nullable=True)
    performance_obligation_id: Mapped[int | None] = fk("performance_obligations.id", nullable=True)
