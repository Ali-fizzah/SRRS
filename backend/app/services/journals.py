"""Journal generation and lifecycle (plan §5.6, §5.7, D12, D13). Tasks P4-T2, P4-T3, P4-T4.

Generation books, for one period: invoices and credit notes by date then number, then catch-up
revenue, then revenue. Each contract is worked out completely in memory, so a contract that cannot
be booked is reported and writes nothing. Lifecycle: DRAFT -> APPROVED -> POSTED; corrections are
new REVERSAL entries, each in a batch of its own that goes through approve and post too.
"""

from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import Select, delete, exists, func, select, update
from sqlalchemy.orm import Session, aliased

from app.audit import write_audit
from app.config import get_settings
from app.engine.journal_rules import (
    GlResolver,
    MappingRow,
    MissingMappingError,
    ProductAccounts,
    position_effect,
    split_invoice,
    split_revenue,
)
from app.engine.money import from_cents, to_cents
from app.engine.periods import period_key
from app.models import (
    AccountingPeriod,
    Contract,
    ContractLine,
    ContractVersion,
    CreditNote,
    GlAccount,
    GlMapping,
    Invoice,
    InvoiceLine,
    JournalBatch,
    JournalEntry,
    JournalLine,
    PerformanceObligation,
    Product,
    RevenueSchedule,
    ScheduleLine,
    UploadFile,
)
from app.models.enums import (
    AccountRole,
    BatchStatus,
    GlAccountType,
    JournalEntryType,
    PeriodStatus,
    ScheduleLineStatus,
)


class JournalRuleError(Exception):
    """A lifecycle rule said no. The API turns it into its error shape (plan §8)."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


@dataclass(frozen=True)
class SkippedJournal:
    contract_code: str
    reason: str  # MISSING_MAPPING, CREDIT_EXCEEDS_DEFERRED
    message: str


@dataclass
class JournalSummary:
    period_key: str
    batch_id: int | None = None
    batch_no: int | None = None
    entries: int = 0
    total_debit: str = "0.00"
    total_credit: str = "0.00"
    drafts_replaced: int = 0
    skipped: list[SkippedJournal] = field(default_factory=list)


@dataclass
class _Line:
    account_id: int
    debit: int = 0
    credit: int = 0
    product_id: int | None = None
    obligation_id: int | None = None
    schedule_line_ids: list[int] = field(default_factory=list)


@dataclass
class _Entry:
    entry_type: JournalEntryType
    entry_date: date
    contract_id: int
    version_id: int
    source_type: str
    source_id: int | None
    upload_id: int | None
    upload_row: int | None
    description: str
    lines: list[_Line]


@dataclass(frozen=True)
class _Document:
    sort_key: tuple[date, str]
    kind: JournalEntryType
    source_id: int
    number: str
    when: date
    amount: int
    upload_id: int | None
    upload_row: int | None
    invoice_id: int


@dataclass(frozen=True)
class _DocumentLine:
    amount: int
    product_id: int | None
    version_id: int | None


@dataclass(frozen=True)
class _RevenueLine:
    id: int
    obligation_id: int
    product_id: int
    line_no: int
    version_id: int
    amount: int
    is_catch_up: bool


# --------------------------------------------------------------------------- generation


def generate_journals(
    db: Session,
    period: str,
    user_id: int,
    report: Callable[[int], None] = lambda progress: None,
) -> JournalSummary:
    """Plan §5.6-5.7. Replaces this period's DRAFT batch, and books whatever no batch holds yet."""
    period_row = db.scalar(
        select(AccountingPeriod).where(AccountingPeriod.period_key == period).with_for_update()
    )
    if period_row is None:
        raise JournalRuleError(404, "NOT_FOUND", f"Period {period} does not exist.")
    summary = JournalSummary(period)
    for batch_id in _generated_drafts(db, period_row.id):
        discard_batch(db, batch_id, user_id, "Regenerated.")
        summary.drafts_replaced += 1
    db.expire_all()
    report(10)

    documents, document_lines = _unbooked_documents(db, period)
    revenue = _unbooked_revenue(db, period)
    contract_ids = sorted(set(documents) | set(revenue))
    report(30)
    if not contract_ids:
        _audit_generation(db, user_id, summary)
        return summary

    resolver = _load_resolver(db)
    products = _load_products(db)
    contract_rows = db.execute(
        select(Contract.id, Contract.contract_code, ContractVersion.id)
        .join(
            ContractVersion,
            (ContractVersion.contract_id == Contract.id)
            & (ContractVersion.version_no == Contract.current_version_no),
        )
        .where(Contract.id.in_(contract_ids))
    ).all()
    codes = {cid: code for cid, code, _ in contract_rows}
    current_version = {cid: vid for cid, _, vid in contract_rows}
    positions = journal_positions(db, contract_ids)
    version_source = _version_sources(db, current_version.values(), revenue)
    report(50)

    planned: list[_Entry] = []
    for contract_id in contract_ids:
        try:
            planned.extend(
                _plan_contract(
                    contract_id,
                    positions.get(contract_id, 0),
                    documents.get(contract_id, []),
                    document_lines,
                    revenue.get(contract_id, []),
                    resolver,
                    products,
                    current_version[contract_id],
                    version_source,
                    period_row.start_date,
                    period_row.end_date,
                    period,
                )
            )
        except MissingMappingError as exc:
            summary.skipped.append(SkippedJournal(codes[contract_id], "MISSING_MAPPING", f"{exc}."))
        except _CreditExceedsDeferredError as exc:
            summary.skipped.append(
                SkippedJournal(codes[contract_id], "CREDIT_EXCEEDS_DEFERRED", str(exc))
            )
    report(70)

    if planned:
        _save_batch(db, period_row.id, user_id, planned, summary)
    report(90)
    _audit_generation(db, user_id, summary)
    return summary


class _CreditExceedsDeferredError(Exception):
    pass


def _audit_generation(db: Session, user_id: int, summary: JournalSummary) -> None:
    write_audit(
        db,
        user_id=user_id,
        action="JOURNALS_GENERATED",
        entity_type="journal_batch",
        entity_id=summary.batch_id,
        after={
            "period_key": summary.period_key,
            "batch_no": summary.batch_no,
            "entries": summary.entries,
            "total_debit": summary.total_debit,
            "total_credit": summary.total_credit,
            "drafts_replaced": summary.drafts_replaced,
            "skipped": [{"contract": s.contract_code, "reason": s.reason} for s in summary.skipped],
        },
    )


def _generated_drafts(db: Session, period_id: int) -> list[int]:
    """DRAFT batches built by generation. Reversal batches are the accountant's own work."""
    reversal_only = ~exists().where(
        JournalEntry.batch_id == JournalBatch.id,
        JournalEntry.entry_type != JournalEntryType.REVERSAL,
    ) & exists().where(JournalEntry.batch_id == JournalBatch.id)
    return list(
        db.scalars(
            select(JournalBatch.id).where(
                JournalBatch.period_id == period_id,
                JournalBatch.status == BatchStatus.DRAFT,
                ~reversal_only,
            )
        )
    )


def discard_batch(db: Session, batch_id: int, user_id: int | None, reason: str) -> None:
    """§5.7: a DRAFT batch is deleted and its schedule lines stop pointing at it."""
    batch = db.get(JournalBatch, batch_id)
    if batch is None or batch.status != BatchStatus.DRAFT:
        raise ValueError(f"batch {batch_id} is not a DRAFT batch")
    entries = select(JournalEntry.id).where(JournalEntry.batch_id == batch_id)
    lines = select(JournalLine.id).where(JournalLine.entry_id.in_(entries))
    db.execute(
        update(ScheduleLine)
        .where(ScheduleLine.journal_line_id.in_(lines))
        .values(journal_line_id=None)
        .execution_options(synchronize_session=False)
    )
    db.execute(
        delete(JournalLine)
        .where(JournalLine.entry_id.in_(entries))
        .execution_options(synchronize_session=False)
    )
    db.execute(
        delete(JournalEntry)
        .where(JournalEntry.batch_id == batch_id)
        .execution_options(synchronize_session=False)
    )
    write_audit(
        db,
        user_id=user_id,
        action="JOURNAL_BATCH_DISCARDED",
        entity_type="journal_batch",
        entity_id=batch_id,
        before={"batch_no": batch.batch_no, "total_debit": str(batch.total_debit)},
        reason=reason,
    )
    db.delete(batch)
    db.flush()


def document_posting_period(document_date: date, upload_period: str | None) -> str:
    """D6: a document dated in a closed period posts to the period open when it was uploaded."""
    document_period = period_key(document_date)
    return max(document_period, upload_period or document_period)


def _unbooked_documents(
    db: Session, period: str
) -> tuple[dict[int, list[_Document]], dict[int, list[_DocumentLine]]]:
    """Invoices and credit notes due by this period that no batch holds yet."""
    documents: dict[int, list[_Document]] = defaultdict(list)
    invoice_ids: set[int] = set()

    booked_invoices = select(JournalEntry.source_id).where(
        JournalEntry.entry_type == JournalEntryType.INVOICE
    )
    for row in db.execute(
        select(
            Invoice.id,
            Invoice.contract_id,
            Invoice.invoice_number,
            Invoice.invoice_date,
            Invoice.total_amount,
            Invoice.source_upload_id,
            Invoice.source_row,
            UploadFile.period_key,
        )
        .outerjoin(UploadFile, UploadFile.id == Invoice.source_upload_id)
        .where(Invoice.id.not_in(booked_invoices))
    ):
        if document_posting_period(row.invoice_date, row.period_key) > period:
            continue
        documents[row.contract_id].append(
            _Document(
                (row.invoice_date, row.invoice_number),
                JournalEntryType.INVOICE,
                row.id,
                row.invoice_number,
                row.invoice_date,
                to_cents(row.total_amount),
                row.source_upload_id,
                row.source_row,
                row.id,
            )
        )
        invoice_ids.add(row.id)

    booked_credits = select(JournalEntry.source_id).where(
        JournalEntry.entry_type == JournalEntryType.CREDIT_NOTE
    )
    for credit in db.execute(
        select(
            CreditNote.id,
            Invoice.contract_id,
            CreditNote.credit_note_number,
            CreditNote.credit_date,
            CreditNote.amount,
            CreditNote.source_upload_id,
            CreditNote.source_row,
            CreditNote.invoice_id,
            UploadFile.period_key,
        )
        .join(Invoice, Invoice.id == CreditNote.invoice_id)
        .outerjoin(UploadFile, UploadFile.id == CreditNote.source_upload_id)
        .where(CreditNote.id.not_in(booked_credits))
    ):
        if document_posting_period(credit.credit_date, credit.period_key) > period:
            continue
        documents[credit.contract_id].append(
            _Document(
                (credit.credit_date, credit.credit_note_number),
                JournalEntryType.CREDIT_NOTE,
                credit.id,
                credit.credit_note_number,
                credit.credit_date,
                to_cents(credit.amount),
                credit.source_upload_id,
                credit.source_row,
                credit.invoice_id,
            )
        )
        invoice_ids.add(credit.invoice_id)

    lines: dict[int, list[_DocumentLine]] = defaultdict(list)
    if invoice_ids:
        for invoice_id, amount, product_id, version_id in db.execute(
            select(
                InvoiceLine.invoice_id,
                InvoiceLine.amount,
                ContractLine.product_id,
                ContractLine.contract_version_id,
            )
            .outerjoin(ContractLine, ContractLine.id == InvoiceLine.contract_line_id)
            .where(InvoiceLine.invoice_id.in_(invoice_ids))
            .order_by(InvoiceLine.invoice_id, InvoiceLine.line_no)
        ).tuples():
            lines[invoice_id].append(_DocumentLine(to_cents(amount), product_id, version_id))
    return documents, lines


def _unbooked_revenue(db: Session, period: str) -> dict[int, list[_RevenueLine]]:
    """§5.4: PENDING lines booked to this period (or left over from an earlier one)."""
    revenue: dict[int, list[_RevenueLine]] = defaultdict(list)
    for row in db.execute(
        select(
            ScheduleLine.id,
            ScheduleLine.amount,
            ScheduleLine.is_catch_up,
            PerformanceObligation.id.label("obligation_id"),
            PerformanceObligation.product_id,
            ContractLine.line_no,
            RevenueSchedule.contract_version_id,
            ContractVersion.contract_id,
        )
        .join(RevenueSchedule, RevenueSchedule.id == ScheduleLine.schedule_id)
        .join(
            PerformanceObligation,
            PerformanceObligation.id == RevenueSchedule.performance_obligation_id,
        )
        .join(ContractLine, ContractLine.id == PerformanceObligation.contract_line_id)
        .join(ContractVersion, ContractVersion.id == RevenueSchedule.contract_version_id)
        .where(
            ScheduleLine.status == ScheduleLineStatus.PENDING,
            ScheduleLine.posting_period <= period,
            ScheduleLine.journal_line_id.is_(None),
            ScheduleLine.amount != 0,
        )
        .order_by(ScheduleLine.id)
    ):
        revenue[row.contract_id].append(
            _RevenueLine(
                row.id,
                row.obligation_id,
                row.product_id,
                row.line_no,
                row.contract_version_id,
                to_cents(row.amount),
                row.is_catch_up,
            )
        )
    return revenue


def _load_resolver(db: Session) -> GlResolver:
    rows = [
        MappingRow(role.value, product_id, category, account_id)
        for role, product_id, category, account_id in db.execute(
            select(
                GlMapping.account_role,
                GlMapping.product_id,
                GlMapping.product_category,
                GlMapping.account_id,
            )
        ).tuples()
    ]
    active = set(db.scalars(select(GlAccount.id).where(GlAccount.is_active)))
    return GlResolver(rows, active)


def _load_products(db: Session) -> dict[int, ProductAccounts]:
    return {
        product_id: ProductAccounts(product_id, code, category, revenue_account_id)
        for product_id, code, category, revenue_account_id in db.execute(
            select(Product.id, Product.product_code, Product.category, Product.revenue_account_id)
        ).tuples()
    }


def journal_positions(db: Session, contract_ids: Sequence[int]) -> dict[int, int]:
    """Each contract's billed minus recognised, according to the journals so far (§5.6).

    Everything in a batch counts, except a reversal that is not posted yet.
    """
    positions: dict[int, int] = defaultdict(int)
    for row in db.execute(_entry_totals().where(JournalEntry.contract_id.in_(contract_ids))):
        positions[row.contract_id] += _effect_of(row)
    return positions


def reversal_effects(db: Session, contract_id: int) -> dict[str, int]:
    """Per period, how posted reversals move this contract's position (billing rollforward)."""
    effects: dict[str, int] = defaultdict(int)
    statement = (
        _entry_totals()
        .add_columns(AccountingPeriod.period_key)
        .join(AccountingPeriod, AccountingPeriod.id == JournalBatch.period_id)
        .where(
            JournalEntry.contract_id == contract_id,
            JournalEntry.entry_type == JournalEntryType.REVERSAL,
        )
        .group_by(AccountingPeriod.period_key)
    )
    for row in db.execute(statement):
        effects[row.period_key] += _effect_of(row)
    return effects


def _entry_totals() -> Select[Any]:
    reversed_entry = aliased(JournalEntry)
    revenue_net = func.sum(JournalLine.credit - JournalLine.debit).filter(
        GlAccount.type == GlAccountType.REVENUE
    )
    return (
        select(
            JournalEntry.contract_id,
            JournalEntry.entry_type,
            reversed_entry.entry_type.label("reversed_type"),
            func.sum(JournalLine.debit).label("total_debit"),
            func.coalesce(revenue_net, 0).label("revenue_net"),
        )
        .join(JournalBatch, JournalBatch.id == JournalEntry.batch_id)
        .join(JournalLine, JournalLine.entry_id == JournalEntry.id)
        .join(GlAccount, GlAccount.id == JournalLine.account_id)
        .outerjoin(reversed_entry, reversed_entry.id == JournalEntry.reverses_entry_id)
        .where(
            (JournalEntry.entry_type != JournalEntryType.REVERSAL)
            | (JournalBatch.status == BatchStatus.POSTED)
        )
        .group_by(JournalEntry.contract_id, JournalEntry.entry_type, reversed_entry.entry_type)
    )


def _effect_of(row: Any) -> int:
    return position_effect(
        row.entry_type.value,
        row.reversed_type.value if row.reversed_type else None,
        to_cents(row.total_debit),
        to_cents(row.revenue_net),
    )


def _version_sources(
    db: Session, current_versions: Any, revenue: dict[int, list[_RevenueLine]]
) -> dict[int, tuple[int | None, int | None]]:
    ids = set(current_versions) | {line.version_id for rows in revenue.values() for line in rows}
    return {
        version_id: (upload_id, row)
        for version_id, upload_id, row in db.execute(
            select(
                ContractVersion.id, ContractVersion.source_upload_id, ContractVersion.source_row
            ).where(ContractVersion.id.in_(ids))
        ).tuples()
    }


def _plan_contract(
    contract_id: int,
    opening: int,
    documents: Sequence[_Document],
    document_lines: dict[int, list[_DocumentLine]],
    revenue: Sequence[_RevenueLine],
    resolver: GlResolver,
    products: dict[int, ProductAccounts],
    current_version: int,
    version_source: dict[int, tuple[int | None, int | None]],
    period_start: date,
    period_end: date,
    period: str,
) -> list[_Entry]:
    """§5.6 order of processing, one running position."""
    entries: list[_Entry] = []
    position = opening
    for document in sorted(documents, key=lambda d: d.sort_key):
        if document.amount == 0:
            continue
        lines = document_lines.get(document.invoice_id, [])
        version = next((line.version_id for line in lines if line.version_id), current_version)
        if document.kind == JournalEntryType.INVOICE:
            journal_lines = []
            for line in lines:
                if line.amount == 0:
                    continue
                product = products.get(line.product_id) if line.product_id else None
                unbilled, deferred = split_invoice(position, line.amount)
                position += line.amount
                journal_lines.extend(
                    _invoice_lines(
                        resolver, product, line.product_id, line.amount, unbilled, deferred
                    )
                )
        else:
            if document.amount > max(position, 0):
                raise _CreditExceedsDeferredError(
                    f"Credit note {document.number} is {from_cents(document.amount)}, more than "
                    f"the {from_cents(max(position, 0))} deferred when it is processed (§5.6, by "
                    "date then number). Nothing was booked for this contract."
                )
            position -= document.amount
            first = lines[0] if lines else None
            product_id = first.product_id if first else None
            product = products.get(product_id) if product_id else None
            journal_lines = [
                _Line(
                    resolver.account(AccountRole.DEFERRED_REVENUE.value, product),
                    debit=document.amount,
                    product_id=product_id,
                ),
                _Line(
                    resolver.account(AccountRole.AR.value, product),
                    credit=document.amount,
                    product_id=product_id,
                ),
            ]
        entries.append(
            _Entry(
                document.kind,
                max(document.when, period_start),
                contract_id,
                version,
                document.kind.value,
                document.source_id,
                document.upload_id,
                document.upload_row,
                f"{document.kind.value.replace('_', ' ').title()} {document.number}",
                journal_lines,
            )
        )

    for entry_type, is_catch_up in (
        (JournalEntryType.REVENUE_CATCH_UP, True),
        (JournalEntryType.REVENUE, False),
    ):
        chosen = [line for line in revenue if line.is_catch_up == is_catch_up]
        if not chosen:
            continue
        journal_lines, position = _revenue_lines(chosen, position, resolver, products)
        if not journal_lines:
            continue
        version = max(line.version_id for line in chosen)
        upload_id, upload_row = version_source.get(version, (None, None))
        label = "Catch-up revenue" if is_catch_up else "Revenue"
        entries.append(
            _Entry(
                entry_type,
                period_end,
                contract_id,
                version,
                "SCHEDULE_LINES",
                None,
                upload_id,
                upload_row,
                f"{label} {period}",
                journal_lines,
            )
        )
    return entries


def _invoice_lines(
    resolver: GlResolver,
    product: ProductAccounts | None,
    product_id: int | None,
    amount: int,
    unbilled: int,
    deferred: int,
) -> list[_Line]:
    lines = [
        _Line(resolver.account(AccountRole.AR.value, product), debit=amount, product_id=product_id)
    ]
    if unbilled:
        lines.append(
            _Line(
                resolver.account(AccountRole.UNBILLED_AR.value, product),
                credit=unbilled,
                product_id=product_id,
            )
        )
    if deferred:
        lines.append(
            _Line(
                resolver.account(AccountRole.DEFERRED_REVENUE.value, product),
                credit=deferred,
                product_id=product_id,
            )
        )
    return lines


def _revenue_lines(
    chosen: Sequence[_RevenueLine],
    position: int,
    resolver: GlResolver,
    products: dict[int, ProductAccounts],
) -> tuple[list[_Line], int]:
    """§5.7: one revenue line per obligation; the debit uses deferred first, then unbilled."""
    by_obligation: dict[int, list[_RevenueLine]] = defaultdict(list)
    for line in chosen:
        by_obligation[line.obligation_id].append(line)

    journal_lines: list[_Line] = []
    for obligation_id, rows in sorted(
        by_obligation.items(), key=lambda item: (item[1][0].line_no, item[0])
    ):
        amount = sum(row.amount for row in rows)
        if amount == 0:
            continue
        product_id = rows[0].product_id
        product = products[product_id]
        ids = [row.id for row in rows]
        revenue_account = resolver.account(AccountRole.REVENUE.value, product)
        common: dict[str, Any] = {"product_id": product_id, "obligation_id": obligation_id}
        deferred_account = resolver.account(AccountRole.DEFERRED_REVENUE.value, product)
        unbilled_account = resolver.account(AccountRole.UNBILLED_AR.value, product)
        if amount > 0:
            from_deferred, from_unbilled = split_revenue(position, amount)
            position -= amount
            if from_deferred:
                journal_lines.append(_Line(deferred_account, debit=from_deferred, **common))
            if from_unbilled:
                journal_lines.append(_Line(unbilled_account, debit=from_unbilled, **common))
            journal_lines.append(
                _Line(revenue_account, credit=amount, schedule_line_ids=ids, **common)
            )
        else:
            # A negative last month (§5.3 can give one on very small amounts) runs the other way.
            to_unbilled, to_deferred = split_invoice(position, -amount)
            position -= amount
            journal_lines.append(
                _Line(revenue_account, debit=-amount, schedule_line_ids=ids, **common)
            )
            if to_unbilled:
                journal_lines.append(_Line(unbilled_account, credit=to_unbilled, **common))
            if to_deferred:
                journal_lines.append(_Line(deferred_account, credit=to_deferred, **common))
    return journal_lines, position


def _save_batch(
    db: Session, period_id: int, user_id: int, planned: list[_Entry], summary: JournalSummary
) -> None:
    total_debit = sum(line.debit for entry in planned for line in entry.lines)
    total_credit = sum(line.credit for entry in planned for line in entry.lines)
    if total_debit != total_credit:  # every entry balances, so this would be a bug here
        raise ValueError(f"unbalanced batch: debit {total_debit}, credit {total_credit}")

    batch = _new_batch(db, period_id, user_id, total_debit, total_credit)
    rows = [
        JournalEntry(
            batch_id=batch.id,
            entry_type=entry.entry_type,
            entry_date=entry.entry_date,
            contract_id=entry.contract_id,
            contract_version_id=entry.version_id,
            source_type=entry.source_type,
            source_id=entry.source_id,
            source_upload_id=entry.upload_id,
            source_row=entry.upload_row,
            description=entry.description,
        )
        for entry in planned
    ]
    db.add_all(rows)
    db.flush()

    pairs = []
    for entry, row in zip(planned, rows, strict=True):
        for line in entry.lines:
            journal_line = JournalLine(
                entry_id=row.id,
                account_id=line.account_id,
                debit=from_cents(line.debit),
                credit=from_cents(line.credit),
                product_id=line.product_id,
                performance_obligation_id=line.obligation_id,
            )
            pairs.append((journal_line, line.schedule_line_ids))
    db.add_all(journal_line for journal_line, _ in pairs)
    db.flush()

    links = [
        {"id": schedule_line_id, "journal_line_id": journal_line.id}
        for journal_line, schedule_line_ids in pairs
        for schedule_line_id in schedule_line_ids
    ]
    if links:
        db.execute(update(ScheduleLine), links)
    summary.batch_id = batch.id
    summary.batch_no = batch.batch_no
    summary.entries = len(rows)
    summary.total_debit = str(from_cents(total_debit))
    summary.total_credit = str(from_cents(total_credit))


def _new_batch(
    db: Session, period_id: int, user_id: int, total_debit: int, total_credit: int
) -> JournalBatch:
    last = db.scalar(
        select(func.max(JournalBatch.batch_no)).where(JournalBatch.period_id == period_id)
    )
    batch = JournalBatch(
        period_id=period_id,
        batch_no=(last or 0) + 1,
        generated_by=user_id,
        total_debit=from_cents(total_debit),
        total_credit=from_cents(total_credit),
    )
    db.add(batch)
    db.flush()
    return batch


# --------------------------------------------------------------------------- lifecycle


def _locked_batch(db: Session, batch_id: int) -> JournalBatch:
    batch = db.scalar(select(JournalBatch).where(JournalBatch.id == batch_id).with_for_update())
    if batch is None:
        raise JournalRuleError(404, "NOT_FOUND", f"Journal batch {batch_id} does not exist.")
    return batch


def _require_status(batch: JournalBatch, expected: BatchStatus, action: str) -> None:
    if batch.status != expected:
        raise JournalRuleError(
            409,
            "BATCH_WRONG_STATUS",
            f"Only a {expected.value} batch can be {action}; this one is {batch.status.value}.",
        )


def _require_period_not_closed(db: Session, batch: JournalBatch) -> None:
    status = db.scalar(
        select(AccountingPeriod.status).where(AccountingPeriod.id == batch.period_id)
    )
    if status == PeriodStatus.CLOSED:
        raise JournalRuleError(409, "PERIOD_CLOSED", "This batch's period is closed.")


def approve_batch(db: Session, batch_id: int, user_id: int) -> JournalBatch:
    """§5.7, D13: the user who generated a batch cannot approve it (setting, on by default)."""
    batch = _locked_batch(db, batch_id)
    _require_status(batch, BatchStatus.DRAFT, "approved")
    _require_period_not_closed(db, batch)
    if get_settings().segregation_of_duties and batch.generated_by == user_id:
        raise JournalRuleError(
            403,
            "SEGREGATION_OF_DUTIES",
            "You generated this batch, so someone else must approve it (D13).",
        )
    if batch.total_debit != batch.total_credit:
        raise JournalRuleError(409, "BATCH_NOT_BALANCED", "Debits do not equal credits.")
    batch.status = BatchStatus.APPROVED
    batch.approved_by = user_id
    batch.approved_at = datetime.now(UTC)
    write_audit(
        db,
        user_id=user_id,
        action="JOURNAL_BATCH_APPROVED",
        entity_type="journal_batch",
        entity_id=batch.id,
        before={"status": BatchStatus.DRAFT.value},
        after={"status": BatchStatus.APPROVED.value},
    )
    db.flush()
    return batch


def send_back_batch(db: Session, batch_id: int, user_id: int, reason: str | None) -> JournalBatch:
    """§5.7: an Approver returns an APPROVED batch to DRAFT."""
    batch = _locked_batch(db, batch_id)
    _require_status(batch, BatchStatus.APPROVED, "sent back")
    before = {"status": batch.status.value, "approved_by": batch.approved_by}
    batch.status = BatchStatus.DRAFT
    batch.approved_by = None
    batch.approved_at = None
    write_audit(
        db,
        user_id=user_id,
        action="JOURNAL_BATCH_SENT_BACK",
        entity_type="journal_batch",
        entity_id=batch.id,
        before=before,
        after={"status": BatchStatus.DRAFT.value},
        reason=reason,
    )
    db.flush()
    return batch


def post_batch(db: Session, batch_id: int, user_id: int) -> JournalBatch:
    """§5.7: POSTED is read-only from here on; the database enforces that (§6.3)."""
    batch = _locked_batch(db, batch_id)
    _require_status(batch, BatchStatus.APPROVED, "posted")
    _require_period_not_closed(db, batch)
    entries = select(JournalEntry.id).where(JournalEntry.batch_id == batch.id)
    lines = select(JournalLine.id).where(JournalLine.entry_id.in_(entries))
    posted_lines = db.execute(
        update(ScheduleLine)
        .where(ScheduleLine.journal_line_id.in_(lines))
        .values(status=ScheduleLineStatus.POSTED)
        .execution_options(synchronize_session=False)
    )
    batch.status = BatchStatus.POSTED
    batch.posted_by = user_id
    batch.posted_at = datetime.now(UTC)
    write_audit(
        db,
        user_id=user_id,
        action="JOURNAL_BATCH_POSTED",
        entity_type="journal_batch",
        entity_id=batch.id,
        before={"status": BatchStatus.APPROVED.value},
        after={
            "status": BatchStatus.POSTED.value,
            "schedule_lines_posted": posted_lines.rowcount,  # type: ignore[attr-defined]
        },
    )
    db.flush()
    return batch


def reverse_entry(db: Session, entry_id: int, user_id: int, reason: str) -> JournalBatch:
    """§5.7: a REVERSAL mirrors a posted entry in the current period, in a new DRAFT batch.

    The original entry, its schedule lines and its source document all stay as they are.
    """
    original = db.scalar(select(JournalEntry).where(JournalEntry.id == entry_id).with_for_update())
    if original is None:
        raise JournalRuleError(404, "NOT_FOUND", f"Journal entry {entry_id} does not exist.")
    status = db.scalar(select(JournalBatch.status).where(JournalBatch.id == original.batch_id))
    if status != BatchStatus.POSTED:
        raise JournalRuleError(
            409, "ENTRY_NOT_POSTED", "Only a posted entry can be reversed; a draft can be rebuilt."
        )
    if original.entry_type == JournalEntryType.REVERSAL:
        raise JournalRuleError(409, "ENTRY_IS_REVERSAL", "A reversal cannot itself be reversed.")
    if db.scalar(select(JournalEntry.id).where(JournalEntry.reverses_entry_id == entry_id)):
        raise JournalRuleError(409, "ALREADY_REVERSED", "This entry already has a reversal.")

    period = db.scalar(
        select(AccountingPeriod).where(
            AccountingPeriod.status.in_([PeriodStatus.OPEN, PeriodStatus.CLOSING])
        )
    )
    if period is None:
        raise JournalRuleError(409, "NO_CURRENT_PERIOD", "No period is open.")

    lines = list(db.scalars(select(JournalLine).where(JournalLine.entry_id == entry_id)))
    debit = sum(to_cents(line.debit) for line in lines)
    credit = sum(to_cents(line.credit) for line in lines)
    batch = _new_batch(db, period.id, user_id, credit, debit)
    reversal = JournalEntry(
        batch_id=batch.id,
        entry_type=JournalEntryType.REVERSAL,
        entry_date=period.end_date,
        contract_id=original.contract_id,
        contract_version_id=original.contract_version_id,
        source_type="JOURNAL_ENTRY",
        source_id=original.id,
        source_upload_id=original.source_upload_id,
        source_row=original.source_row,
        reverses_entry_id=original.id,
        description=f"Reversal of entry {original.id}: {reason}",
    )
    db.add(reversal)
    db.flush()
    db.add_all(
        JournalLine(
            entry_id=reversal.id,
            account_id=line.account_id,
            debit=line.credit,
            credit=line.debit,
            product_id=line.product_id,
            performance_obligation_id=line.performance_obligation_id,
        )
        for line in lines
    )
    write_audit(
        db,
        user_id=user_id,
        action="JOURNAL_ENTRY_REVERSED",
        entity_type="journal_entry",
        entity_id=original.id,
        after={"reversal_entry_id": reversal.id, "batch_id": batch.id},
        reason=reason,
    )
    db.flush()
    return batch
