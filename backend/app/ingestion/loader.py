"""Loader: parse, validate and save one upload (plan §6, §7, task P1-T8).

`load_upload(db, files, user_id)` takes the files of one upload (their
`upload_files` rows already exist) and, in the caller's transaction:
1. builds the `ExistingData` snapshot the validators need, for the codes the upload uses;
2. parses (P1-T6) and validates (P1-T7) the files together;
3. bulk-loads the accepted rows with COPY, keeping source_upload_id / source_row /
   source_payload on every row (CLAUDE.md rule 5);
4. stores every error in validation_errors and sets each file's status and counts.

Performance obligations and revenue schedules are created later by the
recognition run (P2/P3), not here.
"""

from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from psycopg.types.json import Jsonb
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.audit import write_audit
from app.db.base import Base
from app.engine.money import from_cents
from app.ingestion.parser import CellError, FileRejectedError, ParsedRow, parse_rows, read_table
from app.ingestion.templates import TEMPLATES
from app.ingestion.validators import (
    ContractInfo,
    ExistingData,
    InvoiceInfo,
    LineInfo,
    ProductInfo,
    Row,
    validate_batch,
)
from app.models import (
    AccountingPeriod,
    Contract,
    ContractLine,
    ContractVersion,
    CreditNote,
    Customer,
    Delivery,
    GlAccount,
    Invoice,
    InvoiceLine,
    Product,
    SspRule,
    UploadFile,
    ValidationError,
)
from app.models.enums import (
    ContractEventType,
    ContractStatus,
    PeriodStatus,
    RecognitionMethod,
    UploadStatus,
    UploadTemplate,
)
from app.services.billing import contract_position_cents

CENT = Decimal("0.01")
# A blank ssp_valid_from: the product's first SSP applies from the beginning.
SSP_FROM_THE_START = date(1900, 1, 1)


@dataclass(frozen=True)
class UploadSummary:
    upload_id: int
    template: UploadTemplate
    status: UploadStatus
    total_rows: int
    accepted_rows: int
    rejected_rows: int


def load_upload(
    db: Session,
    files: Sequence[tuple[UploadFile, bytes]],
    user_id: int | None,
    report: Callable[[int], None] = lambda progress: None,
) -> list[UploadSummary]:
    """Process every file of one upload. The caller commits.

    `report` receives the percentage done after each stage (plan §10).
    """
    for upload, _ in files:
        upload.status = UploadStatus.VALIDATING
    db.flush()

    file_errors: dict[int, CellError] = {}
    parsed: dict[UploadTemplate, list[ParsedRow]] = {}
    upload_of: dict[UploadTemplate, UploadFile] = {}
    for upload, content in files:
        template = TEMPLATES[upload.template]
        if upload.template in upload_of:
            file_errors[upload.id] = CellError(
                1, "", "E011", f"This upload already has a {upload.template.value} file.", ""
            )
            continue
        try:
            table = read_table(content, upload.original_filename, template)
        except FileRejectedError as exc:
            file_errors[upload.id] = CellError(1, "", exc.code, exc.message, "")
            continue
        parsed[upload.template] = parse_rows(table, template)
        upload_of[upload.template] = upload

    current = db.scalar(
        select(AccountingPeriod.period_key).where(AccountingPeriod.status == PeriodStatus.OPEN)
    )
    if current is None:
        # §5.8: a period in CLOSING blocks new uploads; nothing is loaded.
        for upload, _ in files:
            file_errors.setdefault(
                upload.id,
                CellError(
                    1,
                    "",
                    "E009",
                    "No accounting period is open (the current one is closing), so uploads "
                    "are blocked until the next period opens.",
                    "",
                ),
            )
        parsed = {}
    report(30)

    results = validate_batch(parsed, _existing(db, current, parsed)) if parsed else {}
    report(60)
    if results:
        _Writer(db, current or "", upload_of).write(results)
    report(90)

    summaries = []
    for upload, _ in files:
        rows = results.get(upload.template, []) if upload_of.get(upload.template) is upload else []
        errors = [e for r in rows for e in r.errors]
        if upload.id in file_errors:
            errors = [file_errors[upload.id]]
        _copy(
            db,
            ValidationError,
            ["upload_file_id", "row_number", "column_name", "error_code", "message", "raw_value"],
            (
                (upload.id, e.row_number, e.column or None, e.code, e.message, e.raw_value or None)
                for e in errors
            ),
        )
        accepted = sum(1 for r in rows if r.ok)
        upload.total_rows = len(rows)
        upload.accepted_rows = accepted
        upload.rejected_rows = len(rows) - accepted
        if upload.id in file_errors or (rows and accepted == 0):
            upload.status = UploadStatus.REJECTED
        elif accepted < len(rows):
            upload.status = UploadStatus.PARTIAL
        else:
            upload.status = UploadStatus.ACCEPTED
        summary = UploadSummary(
            upload.id,
            upload.template,
            upload.status,
            upload.total_rows,
            upload.accepted_rows,
            upload.rejected_rows,
        )
        write_audit(
            db,
            user_id=user_id,
            action="UPLOAD_PROCESSED",
            entity_type="upload_file",
            entity_id=upload.id,
            after={
                "template": upload.template.value,
                "status": upload.status.value,
                "total_rows": summary.total_rows,
                "accepted_rows": summary.accepted_rows,
                "rejected_rows": summary.rejected_rows,
            },
        )
        summaries.append(summary)
    db.flush()
    return summaries


# --------------------------------------------------------------------------- COPY


def _copy(db: Session, model: type[Base], columns: list[str], rows: Iterable[Sequence[Any]]) -> int:
    """Bulk insert with PostgreSQL COPY inside the session's transaction.

    Table and column names come from the models, never from user input.
    """
    raw = db.connection().connection.driver_connection
    count = 0
    statement = f"COPY {model.__tablename__} ({', '.join(columns)}) FROM STDIN"
    with raw.cursor() as cursor, cursor.copy(statement) as copy:  # type: ignore[union-attr]
        for row in rows:
            copy.write_row([Jsonb(v) if isinstance(v, dict) else v for v in row])
            count += 1
    return count


# --------------------------------------------------------------------------- snapshot


def _codes(
    parsed: dict[UploadTemplate, list[ParsedRow]], template: UploadTemplate, column: str
) -> set[str]:
    return {r.values[column] for r in parsed.get(template, []) if r.values.get(column) is not None}


def live_lines(
    db: Session, contract_codes: Iterable[str]
) -> dict[str, dict[int, tuple[int, LineInfo]]]:
    """Lines in force per contract: those of the latest NEW/RENEWAL version, with the
    lines added by later UPGRADE versions on top (§5.5). Value: (contract_line_id, info)."""
    codes = list(set(contract_codes))
    if not codes:
        return {}
    query = (
        select(
            Contract.contract_code,
            ContractVersion.version_no,
            ContractVersion.event_type,
            ContractLine.id,
            ContractLine.line_no,
            Product.product_code,
            ContractLine.service_start,
            ContractLine.service_end,
            ContractLine.completion_date,
        )
        .join(ContractVersion, ContractVersion.contract_id == Contract.id)
        .outerjoin(ContractLine, ContractLine.contract_version_id == ContractVersion.id)
        .outerjoin(Product, Product.id == ContractLine.product_id)
        .where(Contract.contract_code.in_(codes))
        .order_by(Contract.contract_code, ContractVersion.version_no)
    )
    out: dict[str, dict[int, tuple[int, LineInfo]]] = defaultdict(dict)
    last_version: dict[str, int] = {}
    for code, version_no, event, line_id, line_no, product, start, end, completion in db.execute(
        query
    ):
        if last_version.get(code) != version_no and event in (
            ContractEventType.NEW,
            ContractEventType.RENEWAL,
        ):
            out[code] = {}  # a new term replaces the lines
        last_version[code] = version_no
        if line_id is not None:
            out[code][line_no] = (line_id, LineInfo(product, start, end, completion))
    return dict(out)


def _existing(
    db: Session, current: str | None, parsed: dict[UploadTemplate, list[ParsedRow]]
) -> ExistingData:
    tpl = UploadTemplate
    customer_codes = _codes(parsed, tpl.CUSTOMERS, "customer_id") | _codes(
        parsed, tpl.CONTRACTS, "customer_id"
    )
    product_codes = _codes(parsed, tpl.PRODUCTS, "product_id") | _codes(
        parsed, tpl.CONTRACT_LINES, "product_id"
    )
    account_codes = _codes(parsed, tpl.PRODUCTS, "revenue_gl_account")
    invoice_numbers = _codes(parsed, tpl.INVOICES, "invoice_number") | _codes(
        parsed, tpl.CREDIT_NOTES, "invoice_number"
    )
    contract_codes = set().union(
        *(
            _codes(parsed, t, "contract_id")
            for t in (tpl.CONTRACTS, tpl.CONTRACT_LINES, tpl.INVOICES, tpl.DELIVERIES)
        )
    )
    contract_codes |= set(
        db.scalars(
            select(Contract.contract_code)
            .join(Invoice, Invoice.contract_id == Contract.id)
            .where(Invoice.invoice_number.in_(invoice_numbers))
        )
    )

    products = {
        code: ProductInfo(separate, RecognitionMethod(method))
        for code, separate, method in db.execute(
            select(
                Product.product_code, Product.is_separate_obligation, Product.recognition_method
            ).where(Product.product_code.in_(product_codes | _line_products(db, contract_codes)))
        )
    }
    lines = live_lines(db, contract_codes)
    contracts = {
        code: ContractInfo(
            customer_code=customer,
            start_date=start,
            end_date=end,
            lines={no: info for no, (_, info) in lines.get(code, {}).items()},
            cancelled=status == ContractStatus.CANCELLED,
        )
        for code, customer, start, end, status in db.execute(
            select(
                Contract.contract_code,
                Customer.customer_code,
                ContractVersion.start_date,
                ContractVersion.end_date,
                Contract.status,
            )
            .join(Customer, Customer.id == Contract.customer_id)
            .join(
                ContractVersion,
                (ContractVersion.contract_id == Contract.id)
                & (ContractVersion.version_no == Contract.current_version_no),
            )
            .where(Contract.contract_code.in_(contract_codes))
        )
    }
    credited = (
        select(CreditNote.invoice_id, func.sum(CreditNote.amount).label("credited"))
        .group_by(CreditNote.invoice_id)
        .subquery()
    )
    invoices = {
        number: InvoiceInfo(code, when, total, credit or Decimal(0))
        for number, code, when, total, credit in db.execute(
            select(
                Invoice.invoice_number,
                Contract.contract_code,
                Invoice.invoice_date,
                Invoice.total_amount,
                credited.c.credited,
            )
            .join(Contract, Contract.id == Invoice.contract_id)
            .outerjoin(credited, credited.c.invoice_id == Invoice.id)
            .where(Invoice.invoice_number.in_(invoice_numbers))
        )
    }
    delivered: dict[tuple[str, int], Decimal] = defaultdict(Decimal)
    line_owner = {
        line_id: (code, no) for code, by_no in lines.items() for no, (line_id, _) in by_no.items()
    }
    if line_owner:
        for line_id, fraction in db.execute(
            select(Delivery.contract_line_id, func.sum(Delivery.units_fraction))
            .where(Delivery.contract_line_id.in_(line_owner))
            .group_by(Delivery.contract_line_id)
        ):
            delivered[line_owner[line_id]] += fraction

    return ExistingData(
        current_period=current or "190001",
        customers=frozenset(
            db.scalars(
                select(Customer.customer_code).where(Customer.customer_code.in_(customer_codes))
            )
        ),
        products=products,
        accounts={
            code: account_type.value
            for code, account_type in db.execute(
                select(GlAccount.account_code, GlAccount.type).where(
                    GlAccount.account_code.in_(account_codes)
                )
            )
        },
        contracts=contracts,
        invoices=invoices,
        credit_notes=frozenset(
            db.scalars(
                select(CreditNote.credit_note_number).where(
                    CreditNote.credit_note_number.in_(
                        _codes(parsed, tpl.CREDIT_NOTES, "credit_note_number")
                    )
                )
            )
        ),
        deliveries=frozenset(
            db.scalars(
                select(Delivery.delivery_code).where(
                    Delivery.delivery_code.in_(_codes(parsed, tpl.DELIVERIES, "delivery_id"))
                )
            )
        ),
        delivered=dict(delivered),
        positions=_positions(db, contract_codes) if tpl.CREDIT_NOTES in parsed else {},
    )


def _positions(db: Session, contract_codes: set[str]) -> dict[str, Decimal]:
    """Billed minus recognised per contract, for the §5.6 credit note check."""
    return {
        code: from_cents(contract_position_cents(db, contract_id))
        for code, contract_id in db.execute(
            select(Contract.contract_code, Contract.id).where(
                Contract.contract_code.in_(contract_codes)
            )
        ).tuples()
    }


def _line_products(db: Session, contract_codes: set[str]) -> set[str]:
    """Products on existing lines of these contracts (deliveries need their method)."""
    if not contract_codes:
        return set()
    return set(
        db.scalars(
            select(Product.product_code)
            .join(ContractLine, ContractLine.product_id == Product.id)
            .join(ContractVersion, ContractVersion.id == ContractLine.contract_version_id)
            .join(Contract, Contract.id == ContractVersion.contract_id)
            .where(Contract.contract_code.in_(contract_codes))
        )
    )


# --------------------------------------------------------------------------- writing


class _Writer:
    """Writes accepted rows in dependency order, resolving codes to ids as it goes."""

    def __init__(
        self, db: Session, current: str, upload_of: dict[UploadTemplate, UploadFile]
    ) -> None:
        self.db = db
        self.current = current
        self.upload_of = upload_of

    def _src(self, template: UploadTemplate, row: Row) -> tuple[int, int, dict[str, str]]:
        return (self.upload_of[template].id, row.row_number, row.raw)

    @staticmethod
    def _ok(rows: list[Row]) -> list[Row]:
        return [r for r in rows if r.ok]

    def _ids(self, column: Any, key: Any, values: Iterable[str]) -> dict[str, int]:
        wanted = list(set(values))
        if not wanted:
            return {}
        return dict(self.db.execute(select(key, column).where(key.in_(wanted))).tuples().all())

    def write(self, results: dict[UploadTemplate, list[Row]]) -> None:
        tpl = UploadTemplate
        self._customers(self._ok(results[tpl.CUSTOMERS]))
        self._products(self._ok(results[tpl.PRODUCTS]))
        self._contracts(self._ok(results[tpl.CONTRACTS]), self._ok(results[tpl.CONTRACT_LINES]))
        self._invoices(self._ok(results[tpl.INVOICES]))
        self._credit_notes(self._ok(results[tpl.CREDIT_NOTES]))
        self._deliveries(self._ok(results[tpl.DELIVERIES]))

    def _customers(self, rows: list[Row]) -> None:
        _copy(
            self.db,
            Customer,
            [
                "customer_code",
                "name",
                "country",
                "source_upload_id",
                "source_row",
                "source_payload",
            ],
            (
                (
                    r.values["customer_id"],
                    r.values["name"],
                    r.values["country"],
                    *self._src(UploadTemplate.CUSTOMERS, r),
                )
                for r in rows
            ),
        )

    def _products(self, rows: list[Row]) -> None:
        if not rows:
            return
        tpl = UploadTemplate.PRODUCTS
        accounts = self._ids(
            GlAccount.id, GlAccount.account_code, (r.values["revenue_gl_account"] for r in rows)
        )
        _copy(
            self.db,
            Product,
            [
                "product_code",
                "name",
                "category",
                "list_price",
                "recognition_method",
                "is_separate_obligation",
                "revenue_account_id",
                "source_upload_id",
                "source_row",
                "source_payload",
            ],
            (
                (
                    v["product_id"],
                    v["name"],
                    v["category"],
                    v["list_price"],
                    v["recognition_method"],
                    v["separate_obligation"],
                    accounts[v["revenue_gl_account"]],
                    *self._src(tpl, r),
                )
                for r in rows
                for v in (r.values,)
            ),
        )
        products = self._ids(
            Product.id, Product.product_code, (r.values["product_id"] for r in rows)
        )
        _copy(
            self.db,
            SspRule,
            [
                "product_id",
                "ssp_source",
                "ssp_value",
                "ssp_pct",
                "valid_from",
                "source_upload_id",
                "source_row",
                "source_payload",
            ],
            (
                (
                    products[v["product_id"]],
                    v["ssp_source"],
                    v["ssp_value"],
                    v["ssp_pct"],
                    v["ssp_valid_from"] or SSP_FROM_THE_START,
                    *self._src(tpl, r),
                )
                for r in rows
                for v in (r.values,)
            ),
        )

    def _contracts(self, headers: list[Row], lines: list[Row]) -> None:
        if not headers:
            return
        db = self.db
        tpl = UploadTemplate
        customers = self._ids(
            Customer.id, Customer.customer_code, (r.values["customer_id"] for r in headers)
        )
        new = [r for r in headers if r.values["event_type"] == ContractEventType.NEW]
        _copy(
            db,
            Contract,
            ["contract_code", "customer_id", "status", "current_version_no"],
            (
                (
                    r.values["contract_id"],
                    customers[r.values["customer_id"]],
                    ContractStatus.ACTIVE.value,
                    0,
                )
                for r in new
            ),
        )
        contracts = dict(
            db.execute(
                select(Contract.contract_code, Contract.id).where(
                    Contract.contract_code.in_([r.values["contract_id"] for r in headers])
                )
            )
            .tuples()
            .all()
        )
        version_no = dict(
            db.execute(
                select(Contract.contract_code, Contract.current_version_no).where(
                    Contract.contract_code.in_(list(contracts))
                )
            )
            .tuples()
            .all()
        )

        lines_of: dict[str, list[Row]] = defaultdict(list)
        for row in lines:
            lines_of[row.values["contract_id"]].append(row)
        net: dict[int, Decimal] = {}
        for row in lines:
            v = row.values
            net[id(row)] = (v["quantity"] * v["unit_price"] - v["discount"]).quantize(
                CENT, ROUND_HALF_UP
            )

        _copy(
            db,
            ContractVersion,
            [
                "contract_id",
                "version_no",
                "event_type",
                "effective_date",
                "start_date",
                "end_date",
                "transaction_price",
                "booked_period",
                "source_upload_id",
                "source_row",
                "source_payload",
            ],
            (
                (
                    contracts[v["contract_id"]],
                    version_no[v["contract_id"]] + 1,
                    v["event_type"],
                    v["effective_date"],
                    v["start_date"],
                    v["end_date"],
                    sum((net[id(line)] for line in lines_of[v["contract_id"]]), Decimal(0)),
                    self.current,
                    *self._src(tpl.CONTRACTS, r),
                )
                for r in headers
                for v in (r.values,)
            ),
        )
        for row in headers:
            code = row.values["contract_id"]
            changes: dict[str, Any] = {"current_version_no": version_no[code] + 1}
            if row.values["event_type"] == ContractEventType.CANCELLATION:
                changes["status"] = ContractStatus.CANCELLED
            db.execute(update(Contract).where(Contract.id == contracts[code]).values(**changes))

        versions = {
            code: vid
            for code, vid in db.execute(
                select(Contract.contract_code, ContractVersion.id)
                .join(
                    ContractVersion,
                    (ContractVersion.contract_id == Contract.id)
                    & (ContractVersion.version_no == Contract.current_version_no),
                )
                .where(Contract.id.in_(list(contracts.values())))
            ).tuples()
        }
        products = self._ids(
            Product.id, Product.product_code, (r.values["product_id"] for r in lines)
        )
        _copy(
            db,
            ContractLine,
            [
                "contract_version_id",
                "line_no",
                "product_id",
                "quantity",
                "unit_price",
                "discount",
                "net_price",
                "service_start",
                "service_end",
                "completion_date",
                "source_upload_id",
                "source_row",
                "source_payload",
            ],
            (
                (
                    versions[v["contract_id"]],
                    v["line_no"],
                    products[v["product_id"]],
                    v["quantity"],
                    v["unit_price"],
                    v["discount"],
                    net[id(r)],
                    v["service_start"],
                    v["service_end"],
                    v["completion_date"],
                    *self._src(tpl.CONTRACT_LINES, r),
                )
                for r in lines
                for v in (r.values,)
            ),
        )

    def _line_ids(self, rows: list[Row]) -> dict[tuple[str, int], int]:
        lines = live_lines(self.db, (r.values["contract_id"] for r in rows))
        return {
            (code, no): line_id
            for code, by_no in lines.items()
            for no, (line_id, _) in by_no.items()
        }

    def _invoices(self, rows: list[Row]) -> None:
        if not rows:
            return
        tpl = UploadTemplate.INVOICES
        contracts = self._ids(
            Contract.id, Contract.contract_code, (r.values["contract_id"] for r in rows)
        )
        first: dict[str, Row] = {}
        totals: dict[str, Decimal] = defaultdict(Decimal)
        for row in rows:
            first.setdefault(row.values["invoice_number"], row)
            totals[row.values["invoice_number"]] += row.values["amount"]
        _copy(
            self.db,
            Invoice,
            [
                "invoice_number",
                "contract_id",
                "invoice_date",
                "total_amount",
                "source_upload_id",
                "source_row",
                "source_payload",
            ],
            (
                (
                    number,
                    contracts[r.values["contract_id"]],
                    r.values["invoice_date"],
                    totals[number],
                    *self._src(tpl, r),
                )
                for number, r in first.items()
            ),
        )
        invoices = self._ids(Invoice.id, Invoice.invoice_number, first)
        line_ids = self._line_ids(rows)
        _copy(
            self.db,
            InvoiceLine,
            [
                "invoice_id",
                "contract_line_id",
                "line_no",
                "amount",
                "source_upload_id",
                "source_row",
                "source_payload",
            ],
            (
                (
                    invoices[v["invoice_number"]],
                    line_ids.get((v["contract_id"], v["line_no"])),
                    v["line_no"],
                    v["amount"],
                    *self._src(tpl, r),
                )
                for r in rows
                for v in (r.values,)
            ),
        )

    def _credit_notes(self, rows: list[Row]) -> None:
        if not rows:
            return
        invoices = self._ids(
            Invoice.id, Invoice.invoice_number, (r.values["invoice_number"] for r in rows)
        )
        _copy(
            self.db,
            CreditNote,
            [
                "credit_note_number",
                "invoice_id",
                "credit_date",
                "amount",
                "reason",
                "source_upload_id",
                "source_row",
                "source_payload",
            ],
            (
                (
                    v["credit_note_number"],
                    invoices[v["invoice_number"]],
                    v["credit_date"],
                    v["amount"],
                    v["reason"],
                    *self._src(UploadTemplate.CREDIT_NOTES, r),
                )
                for r in rows
                for v in (r.values,)
            ),
        )

    def _deliveries(self, rows: list[Row]) -> None:
        if not rows:
            return
        line_ids = self._line_ids(rows)
        _copy(
            self.db,
            Delivery,
            [
                "delivery_code",
                "contract_line_id",
                "delivery_date",
                "units_fraction",
                "source_upload_id",
                "source_row",
                "source_payload",
            ],
            (
                (
                    v["delivery_id"],
                    line_ids[(v["contract_id"], v["line_no"])],
                    v["delivery_date"],
                    v["units_fraction"],
                    *self._src(UploadTemplate.DELIVERIES, r),
                )
                for r in rows
                for v in (r.values,)
            ),
        )
