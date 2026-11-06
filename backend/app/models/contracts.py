"""Contracts, versions, lines, performance obligations and deliveries (plan §6.1)."""

from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Integer, Numeric, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Money, PeriodKey, SourceMixin, fk, pg_enum
from app.models.enums import (
    ContractEventType,
    ContractStatus,
    ObligationStatus,
    RecognitionMethod,
)


class Contract(Base):
    __tablename__ = "contracts"

    contract_code: Mapped[str] = mapped_column(String(64), unique=True)
    customer_id: Mapped[int] = fk("customers.id")
    status: Mapped[ContractStatus] = mapped_column(
        pg_enum(ContractStatus, "contract_status"), server_default=ContractStatus.ACTIVE.value
    )
    current_version_no: Mapped[int] = mapped_column(Integer, server_default=text("1"))


class ContractVersion(SourceMixin, Base):
    """Snapshot created by an event; never edited after creation (CLAUDE.md rule 3-4)."""

    __tablename__ = "contract_versions"
    __table_args__ = (UniqueConstraint("contract_id", "version_no"),)

    contract_id: Mapped[int] = fk("contracts.id")
    version_no: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[ContractEventType] = mapped_column(
        pg_enum(ContractEventType, "contract_event_type")
    )
    effective_date: Mapped[date] = mapped_column(Date)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    transaction_price: Mapped[Money]
    booked_period: Mapped[PeriodKey]


class ContractLine(SourceMixin, Base):
    __tablename__ = "contract_lines"
    __table_args__ = (UniqueConstraint("contract_version_id", "line_no"),)

    contract_version_id: Mapped[int] = fk("contract_versions.id")
    line_no: Mapped[int] = mapped_column(Integer)
    product_id: Mapped[int] = fk("products.id")
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    unit_price: Mapped[Money]
    discount: Mapped[Money] = mapped_column(server_default=text("0"))
    net_price: Mapped[Money]
    service_start: Mapped[date] = mapped_column(Date)
    service_end: Mapped[date] = mapped_column(Date)
    completion_date: Mapped[date | None] = mapped_column(Date)


class PerformanceObligation(Base):
    __tablename__ = "performance_obligations"

    contract_version_id: Mapped[int] = fk("contract_versions.id")
    contract_line_id: Mapped[int] = fk("contract_lines.id")
    product_id: Mapped[int] = fk("products.id")
    method: Mapped[RecognitionMethod] = mapped_column(
        pg_enum(RecognitionMethod, "recognition_method")
    )
    ssp_amount: Mapped[Money]
    allocated_amount: Mapped[Money]
    service_start: Mapped[date] = mapped_column(Date)
    service_end: Mapped[date] = mapped_column(Date)
    completion_date: Mapped[date | None] = mapped_column(Date)
    carried_from_po_id: Mapped[int | None] = fk("performance_obligations.id", nullable=True)
    status: Mapped[ObligationStatus] = mapped_column(
        pg_enum(ObligationStatus, "obligation_status"),
        server_default=ObligationStatus.ACTIVE.value,
    )


class Delivery(SourceMixin, Base):
    """D3: partial deliveries of a point-in-time obligation."""

    __tablename__ = "deliveries"

    delivery_code: Mapped[str] = mapped_column(String(64), unique=True)
    contract_line_id: Mapped[int] = fk("contract_lines.id")
    delivery_date: Mapped[date] = mapped_column(Date)
    units_fraction: Mapped[Decimal] = mapped_column(Numeric(9, 6))
