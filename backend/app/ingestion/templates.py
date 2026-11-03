"""Template registry: the seven upload templates of plan §7.

One description per template (exact snake_case headers in order, type, required,
limits, example) shared by template downloads, the parser (P1-T6), the
validators (P1-T7) and the uploads page (P1-T10).
"""

import csv
import io
from dataclasses import dataclass, field
from enum import StrEnum

from app.models.enums import ContractEventType, RecognitionMethod, SspSource, UploadTemplate


class ColumnType(StrEnum):
    TEXT = "TEXT"
    INTEGER = "INTEGER"
    DECIMAL = "DECIMAL"  # non-money number; `scale` = max decimal places
    MONEY = "MONEY"  # 2 decimal places (D1)
    DATE = "DATE"  # ISO YYYY-MM-DD or a native Excel date (§7)
    CHOICE = "CHOICE"  # one of `choices`
    YES_NO = "YES_NO"  # Y or N


@dataclass(frozen=True)
class Column:
    name: str
    type: ColumnType
    required: bool
    description: str
    example: str
    max_length: int | None = None  # TEXT
    scale: int | None = None  # DECIMAL / MONEY
    choices: tuple[str, ...] = ()  # CHOICE
    default: str | None = None  # used when an optional cell is blank


@dataclass(frozen=True)
class Template:
    name: UploadTemplate
    title: str
    description: str
    columns: tuple[Column, ...] = field(default_factory=tuple)

    @property
    def headers(self) -> list[str]:
        return [c.name for c in self.columns]


def _text(
    name: str, max_length: int, description: str, example: str, *, required: bool = True
) -> Column:
    return Column(name, ColumnType.TEXT, required, description, example, max_length=max_length)


def _date(name: str, description: str, example: str, *, required: bool = True) -> Column:
    return Column(name, ColumnType.DATE, required, description, example)


def _money(
    name: str, description: str, example: str, *, required: bool = True, default: str | None = None
) -> Column:
    return Column(name, ColumnType.MONEY, required, description, example, scale=2, default=default)


def _choice(name: str, values: tuple[str, ...], description: str, example: str) -> Column:
    return Column(name, ColumnType.CHOICE, True, description, example, choices=values)


def _values(enum_cls: type[StrEnum]) -> tuple[str, ...]:
    return tuple(m.value for m in enum_cls)


CONTRACT_ID = "000123-SUB"  # leading zeros on purpose: they must survive (§7)

# Plan §7, in dependency order (multi-file uploads are processed in this order).
TEMPLATES: dict[UploadTemplate, Template] = {
    t.name: t
    for t in (
        Template(
            UploadTemplate.CUSTOMERS,
            "Customers",
            "One row per customer.",
            (
                _text(
                    "customer_id", 64, "Your customer code. Kept exactly as written.", "CUST-0042"
                ),
                _text("name", 255, "Customer name.", "Northwind Traders Ltd"),
                _text("country", 2, "ISO 3166 two-letter country code.", "GB"),
            ),
        ),
        Template(
            UploadTemplate.PRODUCTS,
            "Products",
            "One row per product, with its SSP rule and recognition method.",
            (
                _text("product_id", 128, "Your product code.", "SUB-PRO-12M"),
                _text("name", 255, "Product name.", "Pro subscription, 12 months"),
                _text(
                    "category",
                    64,
                    "Optional product category (used by GL mappings).",
                    "Subscription",
                    required=False,
                ),
                _money("list_price", "List price per unit.", "12000.00"),
                _choice(
                    "ssp_source",
                    _values(SspSource),
                    "Where the standalone selling price comes from (§5.2).",
                    "FIXED",
                ),
                _money(
                    "ssp_value",
                    "SSP per unit. Required when ssp_source is FIXED.",
                    "12000.00",
                    required=False,
                ),
                Column(
                    "ssp_pct",
                    ColumnType.DECIMAL,
                    False,
                    "SSP as a percentage of list price. Required when ssp_source is PCT_OF_LIST.",
                    "",
                    scale=4,
                ),
                _choice(
                    "recognition_method",
                    _values(RecognitionMethod),
                    "How revenue is recognised (§5.3).",
                    "RATABLE_MONTHLY",
                ),
                Column(
                    "separate_obligation",
                    ColumnType.YES_NO,
                    True,
                    "Y if the product is a separate performance obligation; N for setup fees and "
                    "bundle header lines (D4).",
                    "Y",
                ),
                _text(
                    "revenue_gl_account",
                    32,
                    "GL account code that receives this product's revenue.",
                    "4100",
                ),
                _date(
                    "ssp_valid_from",
                    "Date the SSP rule starts to apply. Optional; set it to the first contract "
                    "start that should use this SSP.",
                    "2025-01-01",
                    required=False,
                ),
            ),
        ),
        Template(
            UploadTemplate.CONTRACTS,
            "Contracts",
            "One row per contract event (NEW, RENEWAL, CANCELLATION, UPGRADE).",
            (
                _text(
                    "contract_id", 64, "Your contract code. Kept exactly as written.", CONTRACT_ID
                ),
                _text("customer_id", 64, "Customer code from the customers template.", "CUST-0042"),
                _date("start_date", "Contract term start.", "2025-01-01"),
                _date("end_date", "Contract term end.", "2025-12-31"),
                _choice(
                    "event_type",
                    _values(ContractEventType),
                    "What this row does to the contract (§5.5).",
                    "NEW",
                ),
                _date("effective_date", "Date the event takes effect.", "2025-01-01"),
            ),
        ),
        Template(
            UploadTemplate.CONTRACT_LINES,
            "Contract lines",
            "One row per product on a contract. Upload in the same batch as the contract row.",
            (
                _text("contract_id", 64, "Contract code from the contracts template.", CONTRACT_ID),
                Column(
                    "line_no", ColumnType.INTEGER, True, "Line number within the contract.", "1"
                ),
                _text("product_id", 128, "Product code from the products template.", "SUB-PRO-12M"),
                Column("quantity", ColumnType.DECIMAL, True, "Units sold.", "1", scale=4),
                _money("unit_price", "Price per unit before discount.", "12000.00"),
                _money(
                    "discount",
                    "Discount on the line. Optional, default 0.",
                    "800.00",
                    required=False,
                    default="0",
                ),
                _date("service_start", "First day of service.", "2025-01-01"),
                _date("service_end", "Last day of service.", "2025-12-31"),
                _date(
                    "completion_date",
                    "POINT_IN_TIME products: date the obligation is satisfied. Optional, "
                    "defaults to service_end.",
                    "",
                    required=False,
                ),
            ),
        ),
        Template(
            UploadTemplate.INVOICES,
            "Invoices",
            "One row per invoice line, from the billing system.",
            (
                _text("invoice_number", 64, "Invoice number.", "INV-2025-0001"),
                _text("contract_id", 64, "Contract code the invoice bills.", CONTRACT_ID),
                _date("invoice_date", "Invoice date.", "2025-01-01"),
                Column(
                    "line_no",
                    ColumnType.INTEGER,
                    True,
                    "Contract line this invoice line bills.",
                    "1",
                ),
                _money("amount", "Amount billed on this line.", "11200.00"),
            ),
        ),
        Template(
            UploadTemplate.CREDIT_NOTES,
            "Credit notes",
            "One row per credit note, from the billing system (D7).",
            (
                _text("credit_note_number", 64, "Credit note number.", "CN-2025-0001"),
                _text("invoice_number", 64, "Invoice the credit note reduces.", "INV-2025-0001"),
                _date("credit_date", "Credit note date.", "2025-06-30"),
                _money("amount", "Amount credited.", "4666.67"),
                Column(
                    "reason",
                    ColumnType.TEXT,
                    True,
                    "Why the credit was issued.",
                    "Cancelled from 1 July",
                ),
            ),
        ),
        Template(
            UploadTemplate.DELIVERIES,
            "Deliveries",
            "Partial deliveries of a POINT_IN_TIME line (D3).",
            (
                _text("delivery_id", 64, "Your delivery reference.", "DLV-0001"),
                _text("contract_id", 64, "Contract code.", CONTRACT_ID),
                Column(
                    "line_no", ColumnType.INTEGER, True, "Contract line delivered against.", "2"
                ),
                _date("delivery_date", "Date of the delivery.", "2025-03-31"),
                Column(
                    "units_fraction",
                    ColumnType.DECIMAL,
                    True,
                    "Share of the line delivered, between 0 and 1 (0.25 = a quarter).",
                    "0.25",
                    scale=6,
                ),
            ),
        ),
    )
}


def get_template(name: str) -> Template | None:
    try:
        return TEMPLATES[UploadTemplate(name)]
    except ValueError:
        return None


def template_csv(template: Template) -> str:
    """The downloadable template: header row plus one example row (§7)."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(template.headers)
    writer.writerow([c.example for c in template.columns])
    return out.getvalue()


def template_xlsx(template: Template) -> bytes:
    """The same template as .xlsx, every cell formatted as text so Excel keeps leading zeros."""
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = template.name.value
    for col, column in enumerate(template.columns, start=1):
        header = ws.cell(row=1, column=col, value=column.name)
        header.font = Font(bold=True)
        example = ws.cell(row=2, column=col, value=column.example or None)
        for cell in (header, example):
            cell.number_format = "@"
        # Whole column as text, so rows people type in later keep leading zeros too.
        dimension = ws.column_dimensions[header.column_letter]
        dimension.number_format = "@"
        dimension.width = max(len(column.name), len(column.example)) + 4
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()
