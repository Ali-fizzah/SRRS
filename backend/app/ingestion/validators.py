"""Business-rule validation of parsed uploads (plan §7.1, task P1-T7).

Pure functions: the caller passes `ExistingData`, a snapshot of what is already in
the database, and the rows the parser produced (E001-E003 are already on them).
Templates are checked in the §7 dependency order; a row may refer to rows of an
earlier template in the same upload, but only to rows that passed.

Codes added here: E004-E010, E012-E014. D9: a failed contract row or line
quarantines the whole contract version (E013); an invoice is all-or-nothing too.
"""

from collections import defaultdict
from collections.abc import Callable, Hashable, Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from app.engine.periods import period_bounds
from app.ingestion.parser import CellError, ParsedRow
from app.models.enums import ContractEventType, RecognitionMethod, UploadTemplate

# --------------------------------------------------------------------------- inputs


@dataclass(frozen=True)
class ProductInfo:
    separate: bool
    method: RecognitionMethod


@dataclass(frozen=True)
class LineInfo:
    product_code: str
    service_start: date
    service_end: date
    completion_date: date | None


@dataclass(frozen=True)
class ContractInfo:
    customer_code: str
    start_date: date
    end_date: date
    lines: Mapping[int, LineInfo]  # lines of the current version


@dataclass(frozen=True)
class InvoiceInfo:
    contract_code: str
    invoice_date: date
    total: Decimal
    credited: Decimal = Decimal(0)  # credit notes already loaded against it


@dataclass(frozen=True)
class ExistingData:
    """What the database already holds, as far as validation needs it."""

    current_period: str  # the OPEN period (D6)
    customers: frozenset[str] = frozenset()
    products: Mapping[str, ProductInfo] = field(default_factory=dict)
    accounts: Mapping[str, str] = field(default_factory=dict)  # code -> ASSET/LIABILITY/REVENUE
    contracts: Mapping[str, ContractInfo] = field(default_factory=dict)
    invoices: Mapping[str, InvoiceInfo] = field(default_factory=dict)
    credit_notes: frozenset[str] = frozenset()
    deliveries: frozenset[str] = frozenset()
    delivered: Mapping[tuple[str, int], Decimal] = field(default_factory=dict)  # Σ units_fraction


# --------------------------------------------------------------------------- output


@dataclass
class Row:
    template: UploadTemplate
    row_number: int
    raw: dict[str, str]
    values: dict[str, Any]
    errors: list[CellError]

    @classmethod
    def from_parsed(cls, template: UploadTemplate, parsed: ParsedRow) -> "Row":
        return cls(template, parsed.row_number, parsed.raw, parsed.values, list(parsed.errors))

    @property
    def ok(self) -> bool:
        return not self.errors

    def has(self, *columns: str) -> bool:
        """True when every column parsed (so rules on them can run)."""
        return all(self.values.get(c) is not None for c in columns)

    def fail(self, code: str, column: str, message: str) -> None:
        self.errors.append(
            CellError(self.row_number, column, code, message, self.raw.get(column, ""))
        )


Result = dict[UploadTemplate, list[Row]]


def validate_batch(
    files: Mapping[UploadTemplate, list[ParsedRow]], existing: ExistingData
) -> Result:
    """Validate every file of one upload together, in dependency order (§7)."""
    rows: Result = {t: [Row.from_parsed(t, p) for p in files.get(t, [])] for t in UploadTemplate}
    known = _Known(existing)
    _customers(rows[UploadTemplate.CUSTOMERS], known)
    _products(rows[UploadTemplate.PRODUCTS], known)
    _contracts(rows[UploadTemplate.CONTRACTS], rows[UploadTemplate.CONTRACT_LINES], known)
    _invoices(rows[UploadTemplate.INVOICES], known)
    _credit_notes(rows[UploadTemplate.CREDIT_NOTES], known)
    _deliveries(rows[UploadTemplate.DELIVERIES], known)
    return rows


# --------------------------------------------------------------------------- shared state


class _Known:
    """References that later templates may use: the database plus rows accepted so far."""

    def __init__(self, existing: ExistingData) -> None:
        self.existing = existing
        self.customers: set[str] = set(existing.customers)
        self.products: dict[str, ProductInfo] = dict(existing.products)
        self.contracts: dict[str, ContractInfo] = dict(existing.contracts)
        self.invoices: dict[str, InvoiceInfo] = dict(existing.invoices)
        self.rejected_contracts: set[str] = set()
        self.rejected_invoices: set[str] = set()
        self.period_start = period_bounds(existing.current_period)[0]

    def line(self, contract: str, line_no: int) -> LineInfo | None:
        info = self.contracts.get(contract)
        return info.lines.get(line_no) if info else None


def _flag_duplicates(
    rows: list[Row], key: Callable[[Row], Hashable | None], column: str, label: str
) -> None:
    """E005 on every row whose key appears more than once in the file."""
    seen: dict[Hashable, list[Row]] = defaultdict(list)
    for row in rows:
        k = key(row)
        if k is not None:
            seen[k].append(row)
    for group in seen.values():
        if len(group) > 1:
            numbers = ", ".join(str(r.row_number) for r in group)
            for row in group:
                row.fail(
                    "E005", column, f"{label} appears more than once in this file (rows {numbers})."
                )


def _negative(row: Row, column: str, *, allow_zero: bool = True) -> None:
    """E008 when the amount is below zero (or zero, when not allowed)."""
    value = row.values.get(column)
    if value is None:
        return
    if value < 0 or (not allow_zero and value == 0):
        bound = "zero or more" if allow_zero else "greater than zero"
        row.fail("E008", column, f"{column} must be {bound}.")


def _missing_ref(known: set[str], rejected: set[str], code: str, what: str) -> str | None:
    if code in known:
        return None
    if code in rejected:
        return f"{what} {code} was rejected in this upload."
    return f"{what} {code} does not exist."


# --------------------------------------------------------------------------- customers


def _customers(rows: list[Row], known: _Known) -> None:
    _flag_duplicates(rows, lambda r: r.values.get("customer_id"), "customer_id", "customer_id")
    for row in rows:
        code = row.values.get("customer_id")
        if code in known.existing.customers:
            row.fail("E006", "customer_id", f"Customer {code} already exists.")
        country = row.values.get("country")
        if country is not None:
            if not (len(country) == 2 and country.isascii() and country.isalpha()):
                row.fail("E002", "country", "country must be a two-letter ISO code such as GB.")
            else:
                row.values["country"] = country.upper()
    known.customers.update(r.values["customer_id"] for r in rows if r.ok)


# --------------------------------------------------------------------------- products


def _products(rows: list[Row], known: _Known) -> None:
    _flag_duplicates(rows, lambda r: r.values.get("product_id"), "product_id", "product_id")
    for row in rows:
        code = row.values.get("product_id")
        if code in known.existing.products:
            row.fail(
                "E006",
                "product_id",
                f"Product {code} already exists; change it on the Products page instead.",
            )
        account = row.values.get("revenue_gl_account")
        if account is not None:
            account_type = known.existing.accounts.get(account)
            if account_type is None:
                row.fail("E004", "revenue_gl_account", f"GL account {account} does not exist.")
            elif account_type != "REVENUE":
                row.fail(
                    "E009",
                    "revenue_gl_account",
                    f"GL account {account} is a {account_type} account, not a REVENUE account.",
                )
        source = row.values.get("ssp_source")
        if source == "FIXED" and row.values.get("ssp_value") is None and row.raw["ssp_value"] == "":
            row.fail("E001", "ssp_value", "ssp_value is required when ssp_source is FIXED.")
        if (
            source == "PCT_OF_LIST"
            and row.values.get("ssp_pct") is None
            and row.raw["ssp_pct"] == ""
        ):
            row.fail("E001", "ssp_pct", "ssp_pct is required when ssp_source is PCT_OF_LIST.")
        for column in ("list_price", "ssp_value", "ssp_pct"):
            _negative(row, column)
    for row in rows:
        if row.ok:
            known.products[row.values["product_id"]] = ProductInfo(
                separate=row.values["separate_obligation"],
                method=RecognitionMethod(row.values["recognition_method"]),
            )


# --------------------------------------------------------------------------- contracts + lines


def _contracts(contract_rows: list[Row], line_rows: list[Row], known: _Known) -> None:
    existing = known.existing
    _flag_duplicates(
        contract_rows, lambda r: r.values.get("contract_id"), "contract_id", "contract_id"
    )
    _flag_duplicates(
        line_rows,
        lambda r: (
            (r.values["contract_id"], r.values["line_no"])
            if r.has("contract_id", "line_no")
            else None
        ),
        "line_no",
        "This contract_id and line_no",
    )

    headers: dict[str, Row] = {}
    for row in contract_rows:
        code = row.values.get("contract_id")
        if code is not None:
            headers.setdefault(code, row)
        _contract_row(row, known)

    lines_of: dict[str, list[Row]] = defaultdict(list)
    for row in line_rows:
        code = row.values.get("contract_id")
        if code is None:
            continue
        lines_of[code].append(row)
        header = headers.get(code)
        if header is None:
            if code in existing.contracts:
                row.fail(
                    "E009",
                    "contract_id",
                    f"Lines for contract {code} must be uploaded together with its contract row "
                    "(plan §5.5).",
                )
            else:
                row.fail("E004", "contract_id", f"Contract {code} is not in this upload.")
        _line_row(row, header, known)

    for code, header in headers.items():
        _contract_shape(header, lines_of.get(code, []), known)

    # D9: one failure quarantines every row of that contract version.
    for code, header in headers.items():
        group = [header, *lines_of.get(code, [])]
        failed = [r for r in group if not r.ok]
        if failed:
            first = failed[0]
            where = f"{first.template.value} row {first.row_number}"
            for row in group:
                if row.ok:
                    row.fail(
                        "E013",
                        "contract_id",
                        f"Contract {code} was quarantined because {where} failed.",
                    )
            known.rejected_contracts.add(code)
        elif header.values["event_type"] != ContractEventType.CANCELLATION:
            new_lines = {
                r.values["line_no"]: LineInfo(
                    product_code=r.values["product_id"],
                    service_start=r.values["service_start"],
                    service_end=r.values["service_end"],
                    completion_date=r.values["completion_date"],
                )
                for r in lines_of.get(code, [])
            }
            if header.values["event_type"] == ContractEventType.UPGRADE:
                # §5.5: an upgrade uploads only the added lines; the others continue.
                new_lines = {**existing.contracts[code].lines, **new_lines}
            known.contracts[code] = ContractInfo(
                customer_code=header.values["customer_id"],
                start_date=header.values["start_date"],
                end_date=header.values["end_date"],
                lines=new_lines,
            )


def _contract_row(row: Row, known: _Known) -> None:
    existing = known.existing
    values = row.values
    code = values.get("contract_id")
    customer = values.get("customer_id")
    if customer is not None:
        problem = _missing_ref(known.customers, set(), customer, "Customer")
        if problem:
            row.fail("E004", "customer_id", problem)

    if row.has("start_date", "end_date") and values["end_date"] < values["start_date"]:
        row.fail("E007", "end_date", "end_date is before start_date.")
    elif row.has("start_date", "end_date", "effective_date") and not (
        values["start_date"] <= values["effective_date"] <= values["end_date"]
    ):
        row.fail("E007", "effective_date", "effective_date is outside the contract term.")

    event = values.get("event_type")
    if event is None or code is None:
        return
    current = existing.contracts.get(code)
    if event == ContractEventType.NEW:
        if current is not None:
            row.fail(
                "E006", "contract_id", f"Contract {code} already exists; use RENEWAL or UPGRADE."
            )
        return
    if current is None:
        row.fail(
            "E004", "contract_id", f"Contract {code} does not exist, so it cannot have a {event}."
        )
        return
    if customer is not None and customer != current.customer_code:
        row.fail(
            "E009",
            "customer_id",
            f"Contract {code} belongs to customer {current.customer_code}, not {customer}.",
        )
    if (
        event in (ContractEventType.CANCELLATION, ContractEventType.UPGRADE)
        and row.has("effective_date")
        and values["effective_date"] < known.period_start
    ):
        row.fail(
            "E010",
            "effective_date",
            f"A {event} must take effect in the current period ({existing.current_period}) or "
            "later; earlier periods are closed (D6).",
        )


def _line_row(row: Row, header: Row | None, known: _Known) -> None:
    values = row.values
    if row.has("line_no") and values["line_no"] < 1:
        row.fail("E002", "line_no", "line_no must be 1 or more.")

    product = values.get("product_id")
    info = known.products.get(product) if product is not None else None
    if product is not None and info is None:
        row.fail("E004", "product_id", f"Product {product} does not exist.")

    _negative(row, "quantity", allow_zero=False)
    _negative(row, "unit_price")
    _negative(row, "discount")
    if (
        row.has("quantity", "unit_price", "discount")
        and row.ok
        and values["discount"] > values["quantity"] * values["unit_price"]
    ):
        row.fail("E009", "discount", "discount is larger than quantity × unit_price.")

    if row.has("service_start", "service_end"):
        start, end = values["service_start"], values["service_end"]
        if end < start:
            row.fail("E007", "service_end", "service_end is before service_start.")
        else:
            if (
                header is not None
                and header.has("start_date", "end_date")
                and not (header.values["start_date"] <= start and end <= header.values["end_date"])
            ):
                row.fail(
                    "E007",
                    "service_start",
                    "The service window is outside the contract term "
                    f"({header.values['start_date']} to {header.values['end_date']}).",
                )
            if info is not None and info.method == RecognitionMethod.RATABLE_MONTHLY:
                month_end = period_bounds(f"{end.year:04d}{end.month:02d}")[1]
                if start.day != 1 or end != month_end:
                    row.fail(
                        "E012",
                        "service_start",
                        "RATABLE_MONTHLY lines must start on the 1st and end on a month end.",
                    )
        completion = values.get("completion_date")
        if completion is not None and completion < start:
            row.fail("E007", "completion_date", "completion_date is before service_start.")


def _contract_shape(header: Row, lines: list[Row], known: _Known) -> None:
    """Rules about the contract as a whole (§5.2, §5.5)."""
    event = header.values.get("event_type")
    code = header.values.get("contract_id")
    if event is None:
        return
    if event == ContractEventType.CANCELLATION:
        if lines:
            header.fail("E009", "event_type", "A CANCELLATION has no contract lines (plan §5.5).")
        return
    if not lines:
        header.fail(
            "E009",
            "event_type",
            f"Contract {code} ({event}) has no lines; upload them in the same batch (plan §5.5).",
        )
        return
    current = known.existing.contracts.get(code) if code is not None else None
    if event == ContractEventType.UPGRADE and current is not None:
        for row in lines:
            if row.has("line_no") and row.values["line_no"] in current.lines:
                row.fail(
                    "E009",
                    "line_no",
                    f"An UPGRADE uploads only added lines; contract {code} already has line "
                    f"{row.values['line_no']} (plan §5.5).",
                )
    products = [known.products.get(r.values["product_id"]) for r in lines if r.has("product_id")]
    if (
        event in (ContractEventType.NEW, ContractEventType.RENEWAL)
        and products
        and all(p is not None for p in products)
        and not any(p.separate for p in products if p is not None)
    ):
        header.fail(
            "E014",
            "contract_id",
            f"Contract {code} has no line whose product is a separate performance obligation.",
        )


# --------------------------------------------------------------------------- invoices


def _invoices(rows: list[Row], known: _Known) -> None:
    _flag_duplicates(
        rows,
        lambda r: (
            (r.values["invoice_number"], r.values["line_no"])
            if r.has("invoice_number", "line_no")
            else None
        ),
        "line_no",
        "This invoice_number and line_no",
    )
    groups: dict[str, list[Row]] = defaultdict(list)
    for row in rows:
        number = row.values.get("invoice_number")
        if number is not None:
            groups[number].append(row)
        if number in known.existing.invoices:
            row.fail("E006", "invoice_number", f"Invoice {number} already exists.")
        _negative(row, "amount")
        _reference_line(row, known)

    for number, group in groups.items():
        first = group[0].values
        for row in group[1:]:
            for column in ("contract_id", "invoice_date"):
                if row.values.get(column) not in (None, first.get(column)):
                    row.fail(
                        "E009",
                        column,
                        f"Every row of invoice {number} must have the same {column}.",
                    )
        failed = [r for r in group if not r.ok]
        if failed:
            for row in group:
                if row.ok:
                    row.fail(
                        "E013",
                        "invoice_number",
                        f"Invoice {number} was not loaded because row "
                        f"{failed[0].row_number} failed.",
                    )
            known.rejected_invoices.add(number)
        else:
            known.invoices[number] = InvoiceInfo(
                contract_code=first["contract_id"],
                invoice_date=first["invoice_date"],
                total=sum((r.values["amount"] for r in group), Decimal(0)),
            )


def _reference_line(row: Row, known: _Known) -> LineInfo | None:
    """E004 unless contract_id + line_no name a line known now. Returns that line."""
    contract = row.values.get("contract_id")
    if contract is None:
        return None
    problem = _missing_ref(set(known.contracts), known.rejected_contracts, contract, "Contract")
    if problem:
        row.fail("E004", "contract_id", problem)
        return None
    line_no = row.values.get("line_no")
    if line_no is None:
        return None
    line = known.line(contract, line_no)
    if line is None:
        row.fail("E004", "line_no", f"Contract {contract} has no line {line_no}.")
    return line


# --------------------------------------------------------------------------- credit notes


def _credit_notes(rows: list[Row], known: _Known) -> None:
    _flag_duplicates(
        rows,
        lambda r: r.values.get("credit_note_number"),
        "credit_note_number",
        "credit_note_number",
    )
    remaining = {n: i.total - i.credited for n, i in known.invoices.items()}
    for row in rows:
        number = row.values.get("credit_note_number")
        if number in known.existing.credit_notes:
            row.fail("E006", "credit_note_number", f"Credit note {number} already exists.")
        _negative(row, "amount")
        invoice_no = row.values.get("invoice_number")
        if invoice_no is None:
            continue
        problem = _missing_ref(set(known.invoices), known.rejected_invoices, invoice_no, "Invoice")
        if problem:
            row.fail("E004", "invoice_number", problem)
            continue
        invoice = known.invoices[invoice_no]
        if row.has("credit_date") and row.values["credit_date"] < invoice.invoice_date:
            row.fail(
                "E007",
                "credit_date",
                f"credit_date is before the invoice date ({invoice.invoice_date}).",
            )
        if row.has("amount") and row.ok:
            if row.values["amount"] > remaining[invoice_no]:
                row.fail(
                    "E009",
                    "amount",
                    f"The credit is more than is left on invoice {invoice_no} "
                    f"({remaining[invoice_no]}).",
                )
            else:
                remaining[invoice_no] -= row.values["amount"]


# --------------------------------------------------------------------------- deliveries


def _deliveries(rows: list[Row], known: _Known) -> None:
    _flag_duplicates(rows, lambda r: r.values.get("delivery_id"), "delivery_id", "delivery_id")
    delivered: dict[tuple[str, int], Decimal] = defaultdict(Decimal, known.existing.delivered)
    for row in rows:
        code = row.values.get("delivery_id")
        if code in known.existing.deliveries:
            row.fail("E006", "delivery_id", f"Delivery {code} already exists.")
        _negative(row, "units_fraction", allow_zero=False)
        line = _reference_line(row, known)
        if line is None:
            continue
        product = known.products.get(line.product_code)
        if (
            product is None
            or not product.separate
            or product.method != RecognitionMethod.POINT_IN_TIME
        ):
            row.fail(
                "E009",
                "line_no",
                "Deliveries can only be recorded on a POINT_IN_TIME line that is a separate "
                "obligation (D3).",
            )
            continue
        when = row.values.get("delivery_date")
        if when is not None:
            completion = line.completion_date or line.service_end
            if when < line.service_start:
                row.fail(
                    "E007", "delivery_date", "delivery_date is before the line's service_start."
                )
            elif when > completion:
                row.fail(
                    "E009",
                    "delivery_date",
                    f"delivery_date is after the line's completion date ({completion}).",
                )
        if row.ok:
            key = (row.values["contract_id"], row.values["line_no"])
            total = delivered[key] + row.values["units_fraction"]
            if total > 1:
                row.fail(
                    "E009",
                    "units_fraction",
                    f"Deliveries on this line would add up to {total}, more than 1 (plan §5.3).",
                )
            else:
                delivered[key] = total
