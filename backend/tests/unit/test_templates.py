"""P1-T5: the template registry matches plan §7 and its examples are valid."""

import csv
import importlib.util
import io
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import openpyxl
import pytest

from app.ingestion.templates import (
    TEMPLATES,
    Column,
    ColumnType,
    Template,
    get_template,
    template_csv,
    template_xlsx,
)

# Plan §7, copied by hand: (headers in order, optional columns).
PLAN_7 = {
    "customers": (["customer_id", "name", "country"], set()),
    "products": (
        [
            "product_id", "name", "category", "list_price", "ssp_source", "ssp_value", "ssp_pct",
            "recognition_method", "separate_obligation", "revenue_gl_account", "ssp_valid_from",
        ],
        {"category", "ssp_value", "ssp_pct", "ssp_valid_from"},
    ),
    "contracts": (
        ["contract_id", "customer_id", "start_date", "end_date", "event_type", "effective_date"],
        set(),
    ),
    "contract_lines": (
        [
            "contract_id", "line_no", "product_id", "quantity", "unit_price", "discount",
            "service_start", "service_end", "completion_date",
        ],
        {"discount", "completion_date"},
    ),
    "invoices": (["invoice_number", "contract_id", "invoice_date", "line_no", "amount"], set()),
    "credit_notes": (
        ["credit_note_number", "invoice_number", "credit_date", "amount", "reason"],
        set(),
    ),
    "deliveries": (
        ["delivery_id", "contract_id", "line_no", "delivery_date", "units_fraction"],
        set(),
    ),
}  # fmt: skip

DEPENDENCY_ORDER = [
    "customers", "products", "contracts", "contract_lines", "invoices", "credit_notes",
    "deliveries",
]  # fmt: skip

ALL = list(TEMPLATES.values())


def test_seven_templates_in_dependency_order() -> None:
    assert [t.name.value for t in ALL] == DEPENDENCY_ORDER


@pytest.mark.parametrize("template", ALL, ids=lambda t: t.name.value)
def test_headers_and_required_match_plan(template: Template) -> None:
    headers, optional = PLAN_7[template.name.value]
    assert template.headers == headers
    assert {c.name for c in template.columns if not c.required} == optional


def test_discount_defaults_to_zero() -> None:
    lines = TEMPLATES[next(t for t in TEMPLATES if t.value == "contract_lines")]
    discount = next(c for c in lines.columns if c.name == "discount")
    assert discount.default == "0"


def _check_value(column: Column, value: str) -> None:
    if column.type is ColumnType.TEXT:
        assert column.max_length is None or len(value) <= column.max_length
    elif column.type is ColumnType.INTEGER:
        int(value)
    elif column.type in (ColumnType.MONEY, ColumnType.DECIMAL):
        number = Decimal(value)
        assert column.scale is not None
        assert -number.as_tuple().exponent <= column.scale  # type: ignore[operator]
        if column.type is ColumnType.MONEY:
            assert column.scale == 2  # D1
    elif column.type is ColumnType.DATE:
        date.fromisoformat(value)
    elif column.type is ColumnType.CHOICE:
        assert value in column.choices
    elif column.type is ColumnType.YES_NO:
        assert value in ("Y", "N")


@pytest.mark.parametrize("template", ALL, ids=lambda t: t.name.value)
def test_example_row_is_valid(template: Template) -> None:
    for column in template.columns:
        if column.required:
            assert column.example, f"{template.name}.{column.name} needs an example"
        if column.example:
            _check_value(column, column.example)


def test_csv_has_header_and_example_row_and_keeps_leading_zeros() -> None:
    template = get_template("contracts")
    assert template is not None
    rows = list(csv.reader(io.StringIO(template_csv(template))))
    assert rows[0] == template.headers
    assert rows[1][0] == "000123-SUB"
    assert len(rows) == 2


def test_xlsx_cells_are_text_formatted() -> None:
    template = get_template("contract_lines")
    assert template is not None
    wb = openpyxl.load_workbook(io.BytesIO(template_xlsx(template)))
    ws = wb.active
    assert ws is not None
    assert [c.value for c in ws[1]] == template.headers
    assert ws["A2"].value == "000123-SUB" and ws["A2"].number_format == "@"
    assert ws.column_dimensions["A"].number_format == "@"


def test_unknown_template() -> None:
    assert get_template("payments") is None


def test_excel_converter_writes_the_same_headers() -> None:
    """benchmarks/tools/convert_revrec_xlsx.py must produce files the system accepts."""
    path = Path(__file__).resolve().parents[3] / "benchmarks" / "tools" / "convert_revrec_xlsx.py"
    spec = importlib.util.spec_from_file_location("convert_revrec_xlsx", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    for name, headers in module.TEMPLATES.items():
        template = get_template(name)
        assert template is not None, name
        assert headers == template.headers, name
