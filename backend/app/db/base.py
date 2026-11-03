"""Declarative base, shared column types and mixins for all models (plan §6)."""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    MetaData,
    Numeric,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

# Stable constraint names so later migrations can refer to them (CLAUDE.md rule 7).
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

# D1: money is NUMERIC(18,2) in PostgreSQL and Decimal in Python. Never float.
Money = Annotated[Decimal, mapped_column(Numeric(18, 2))]
PeriodKey = Annotated[str, mapped_column(String(6))]  # D14: YYYYMM


def pg_enum(enum_cls: type[StrEnum], name: str) -> Enum:
    """Native PostgreSQL ENUM storing the member values."""
    return Enum(
        enum_cls,
        name=name,
        values_callable=lambda e: [m.value for m in e],
        validate_strings=True,
    )


def fk(target: str, *, nullable: bool = False, ondelete: str | None = None) -> Any:
    """Indexed foreign key column (plan §6.2: index all FKs)."""
    return mapped_column(
        BigInteger, ForeignKey(target, ondelete=ondelete), nullable=nullable, index=True
    )


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, sort_order=-1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SourceMixin:
    """`src` columns: traceability back to the uploaded file and row (CLAUDE.md rule 5)."""

    @declared_attr
    def source_upload_id(cls) -> Mapped[int | None]:
        column: Mapped[int | None] = fk("upload_files.id", nullable=True)
        return column

    source_row: Mapped[int | None] = mapped_column(Integer)
    source_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
