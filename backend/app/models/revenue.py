"""Revenue schedules and schedule lines (plan §6.1, §5.4)."""

from sqlalchemy import Index, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Money, PeriodKey, fk, pg_enum
from app.models.enums import ScheduleLineStatus, ScheduleStatus


class RevenueSchedule(Base):
    __tablename__ = "revenue_schedules"

    performance_obligation_id: Mapped[int] = fk("performance_obligations.id")
    contract_version_id: Mapped[int] = fk("contract_versions.id")
    status: Mapped[ScheduleStatus] = mapped_column(
        pg_enum(ScheduleStatus, "schedule_status"), server_default=ScheduleStatus.ACTIVE.value
    )
    generated_by_job_id: Mapped[int | None] = fk("job_runs.id", nullable=True)


class ScheduleLine(Base):
    """D5: service_period = when earned; posting_period = when booked."""

    __tablename__ = "schedule_lines"
    __table_args__ = (Index("ix_schedule_lines_status_service_period", "status", "service_period"),)

    schedule_id: Mapped[int] = fk("revenue_schedules.id")
    service_period: Mapped[PeriodKey]
    amount: Mapped[Money]
    status: Mapped[ScheduleLineStatus] = mapped_column(
        pg_enum(ScheduleLineStatus, "schedule_line_status"),
        server_default=ScheduleLineStatus.PENDING.value,
    )
    posting_period: Mapped[PeriodKey | None] = mapped_column(index=True)
    is_catch_up: Mapped[bool] = mapped_column(server_default=text("false"))
    journal_line_id: Mapped[int | None] = fk("journal_lines.id", nullable=True)
