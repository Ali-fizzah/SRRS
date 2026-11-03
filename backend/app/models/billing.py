"""Billing documents received from the billing system (plan §6.1, D7)."""

from datetime import date

from sqlalchemy import Date, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Money, SourceMixin, fk


class Invoice(SourceMixin, Base):
    __tablename__ = "invoices"

    invoice_number: Mapped[str] = mapped_column(String(64), unique=True)
    contract_id: Mapped[int] = fk("contracts.id")
    invoice_date: Mapped[date] = mapped_column(Date)
    total_amount: Mapped[Money]


class InvoiceLine(SourceMixin, Base):
    """One row of the invoices template; keeps its own source row (CLAUDE.md rule 5)."""

    __tablename__ = "invoice_lines"
    __table_args__ = (UniqueConstraint("invoice_id", "line_no"),)

    invoice_id: Mapped[int] = fk("invoices.id")
    contract_line_id: Mapped[int | None] = fk("contract_lines.id", nullable=True)
    line_no: Mapped[int] = mapped_column(Integer)
    amount: Mapped[Money]


class CreditNote(SourceMixin, Base):
    __tablename__ = "credit_notes"

    credit_note_number: Mapped[str] = mapped_column(String(64), unique=True)
    invoice_id: Mapped[int] = fk("invoices.id")
    credit_date: Mapped[date] = mapped_column(Date)
    amount: Mapped[Money]
    reason: Mapped[str] = mapped_column(Text)
