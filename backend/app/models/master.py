"""Master data: customers, products, SSP history, chart of accounts, GL mappings (plan §6.1)."""

from datetime import date
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Money, SourceMixin, fk, pg_enum
from app.models.enums import AccountRole, GlAccountType, RecognitionMethod, SspSource


class Customer(SourceMixin, Base):
    __tablename__ = "customers"

    customer_code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    country: Mapped[str] = mapped_column(String(2))


class GlAccount(Base):
    __tablename__ = "gl_accounts"

    account_code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    type: Mapped[GlAccountType] = mapped_column(pg_enum(GlAccountType, "gl_account_type"))
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))


class Product(SourceMixin, Base):
    __tablename__ = "products"

    product_code: Mapped[str] = mapped_column(String(128), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    category: Mapped[str | None] = mapped_column(String(64))
    list_price: Mapped[Money]
    recognition_method: Mapped[RecognitionMethod] = mapped_column(
        pg_enum(RecognitionMethod, "recognition_method")
    )
    is_separate_obligation: Mapped[bool]
    revenue_account_id: Mapped[int] = fk("gl_accounts.id")


class SspRule(SourceMixin, Base):
    """SSP history per product; rows are added, never overwritten (plan §5.2)."""

    __tablename__ = "ssp_rules"
    __table_args__ = (
        CheckConstraint("ssp_source <> 'FIXED' OR ssp_value IS NOT NULL", name="fixed_needs_value"),
        CheckConstraint("ssp_source <> 'PCT_OF_LIST' OR ssp_pct IS NOT NULL", name="pct_needs_pct"),
        CheckConstraint("valid_to IS NULL OR valid_to >= valid_from", name="valid_range"),
    )

    product_id: Mapped[int] = fk("products.id")
    ssp_source: Mapped[SspSource] = mapped_column(pg_enum(SspSource, "ssp_source"))
    ssp_value: Mapped[Money | None]
    ssp_pct: Mapped[Decimal | None] = mapped_column(Numeric(7, 4))
    valid_from: Mapped[date] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)


class GlMapping(Base):
    """D12: role -> account, precedence product > category > default (both NULL)."""

    __tablename__ = "gl_mappings"
    __table_args__ = (
        CheckConstraint(
            "product_id IS NULL OR product_category IS NULL", name="product_or_category"
        ),
        UniqueConstraint(
            "account_role",
            "product_id",
            "product_category",
            postgresql_nulls_not_distinct=True,
        ),
    )

    account_role: Mapped[AccountRole] = mapped_column(pg_enum(AccountRole, "account_role"))
    product_id: Mapped[int | None] = fk("products.id", nullable=True)
    product_category: Mapped[str | None] = mapped_column(String(64))
    account_id: Mapped[int] = fk("gl_accounts.id")
