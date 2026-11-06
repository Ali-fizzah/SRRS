"""Users and roles, uploads, validation errors, jobs and the audit log (plan §6.1)."""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Index, Integer, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PeriodKey, fk, pg_enum
from app.models.enums import JobStatus, JobType, UploadStatus, UploadTemplate


class User(Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True)
    full_name: Mapped[str] = mapped_column(String(255))
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))


class Role(Base):
    __tablename__ = "roles"

    name: Mapped[str] = mapped_column(String(32), unique=True)


class UserRole(Base):
    __tablename__ = "user_roles"
    __table_args__ = (UniqueConstraint("user_id", "role_id"),)

    user_id: Mapped[int] = fk("users.id")
    role_id: Mapped[int] = fk("roles.id")


class UploadFile(Base):
    __tablename__ = "upload_files"

    template: Mapped[UploadTemplate] = mapped_column(pg_enum(UploadTemplate, "upload_template"))
    original_filename: Mapped[str] = mapped_column(String(255))
    sha256: Mapped[str] = mapped_column(String(64))
    stored_path: Mapped[str] = mapped_column(String(1024))
    uploaded_by: Mapped[int] = fk("users.id")
    period_key: Mapped[PeriodKey]
    status: Mapped[UploadStatus] = mapped_column(
        pg_enum(UploadStatus, "upload_status"), server_default=UploadStatus.RECEIVED.value
    )
    total_rows: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    accepted_rows: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    rejected_rows: Mapped[int] = mapped_column(Integer, server_default=text("0"))


class ValidationError(Base):
    __tablename__ = "validation_errors"

    upload_file_id: Mapped[int] = fk("upload_files.id")
    row_number: Mapped[int] = mapped_column(Integer)
    column_name: Mapped[str | None] = mapped_column(String(64))
    error_code: Mapped[str] = mapped_column(String(4))  # E001-E014 (plan §7.1)
    message: Mapped[str] = mapped_column(Text)
    raw_value: Mapped[str | None] = mapped_column(Text)


class JobRun(Base):
    """D10: Postgres-backed job queue (plan §10)."""

    __tablename__ = "job_runs"
    # The worker claims the oldest QUEUED job.
    __table_args__ = (Index("ix_job_runs_status_created_at", "status", "created_at"),)

    job_type: Mapped[JobType] = mapped_column(pg_enum(JobType, "job_type"))
    status: Mapped[JobStatus] = mapped_column(
        pg_enum(JobStatus, "job_status"), server_default=JobStatus.QUEUED.value
    )
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    progress: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = fk("users.id", nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditLog(Base):
    """Append-only record of every state change (CLAUDE.md rule 8)."""

    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_log_entity", "entity_type", "entity_id"),)

    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    user_id: Mapped[int | None] = fk("users.id", nullable=True)
    action: Mapped[str] = mapped_column(String(64))
    entity_type: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    reason: Mapped[str | None] = mapped_column(Text)
