"""P1-T6: reading CSV/XLSX uploads as strings and parsing cell types (plan §7)."""

import io
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from openpyxl import Workbook

from app.ingestion.parser import FileRejectedError, parse_rows, read_table
from app.ingestion.templates import TEMPLATES, get_template, template_csv, template_xlsx
from app.models.enums import UploadTemplate

REPO = Path(__file__).resolve().parents[3]

CUSTOMERS = TEMPLATES[UploadTemplate.CUSTOMERS]
CONTRACTS = TEMPLATES[UploadTemplate.CONTRACTS]
LINES = TEMPLATES[UploadTemplate.CONTRACT_LINES]
PRODUCTS = TEMPLATES[UploadTemplate.PRODUCTS]

LINE_HEADER = ",".join(LINES.headers)


def csv_bytes(*lines: str, bom: bool = False) -> bytes:
    data = "\r\n".join(lines).encode()
    return (b"\xef\xbb\xbf" + data) if bom else data


def xlsx_bytes(rows: list[list[Any]], formats: dict[str, str] | None = None) -> bytes:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    for row in rows:
        ws.append(row)
    for coordinate, number_format in (formats or {}).items():
        ws[coordinate].number_format = number_format
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def only_row(content: bytes, filename: str, template=LINES):  # type: ignore[no-untyped-def]
    (row,) = parse_rows(read_table(content, filename, template), template)
    return row


# --------------------------------------------------------------------------- acceptance cases


def test_leading_zeros_survive_csv() -> None:
    row = only_row(
        csv_bytes(LINE_HEADER, "005984698-INV_106000493,1,00042,1,10.00,,2025-01-01,2025-12-31,"),
        "lines.csv",
    )
    assert row.values["contract_id"] == "005984698-INV_106000493"
    assert row.values["product_id"] == "00042"


def test_leading_zeros_survive_xlsx_text_cells() -> None:
    content = xlsx_bytes(
        [LINES.headers, ["000123", 1, "007", 1, 10, None, "2025-01-01", "2025-12-31", None]]
    )
    row = only_row(content, "lines.xlsx")
    assert row.ok, row.errors
    assert row.values["contract_id"] == "000123"
    assert row.values["product_id"] == "007"


def test_native_excel_dates_and_serial_numbers() -> None:
    content = xlsx_bytes(
        [
            LINES.headers,
            # service_start is a real date cell; service_end lost its date format (45657).
            ["C1", 1, "P1", 1, 10, 0, datetime(2025, 1, 1), 45657, None],
        ]
    )
    row = only_row(content, "lines.xlsx")
    assert row.ok, row.errors
    assert row.values["service_start"] == date(2025, 1, 1)
    assert row.values["service_end"] == date(2024, 12, 31)


def test_excel_serial_in_csv() -> None:
    row = only_row(csv_bytes(LINE_HEADER, "C1,1,P1,1,10,,45658,45658.0,"), "lines.csv")
    assert row.values["service_start"] == date(2025, 1, 1)
    assert row.values["service_end"] == date(2025, 1, 1)


def test_bom_is_removed_from_csv() -> None:
    table = read_table(
        csv_bytes("customer_id,name,country", "C1,Acme,GB", bom=True), "c.csv", CUSTOMERS
    )
    assert list(table.frame.columns) == ["customer_id", "name", "country"]
    assert table.frame.iloc[0]["customer_id"] == "C1"


def test_blank_trailing_rows_are_skipped_and_row_numbers_kept() -> None:
    content = csv_bytes(
        "customer_id,name,country", "C1,Acme,GB", ",,", "C2,Beta,US", ",,", "", ",  ,", ""
    )
    table = read_table(content, "c.csv", CUSTOMERS)
    assert table.frame["customer_id"].tolist() == ["C1", "C2"]
    assert table.row_numbers == [2, 4]  # the blank row 3 still counts


def test_blank_trailing_rows_and_columns_in_xlsx() -> None:
    content = xlsx_bytes(
        [
            ["customer_id", "name", "country", None, None],
            ["C1", "Acme", "GB", None, None],
            [None, None, None, None, None],
            [None, None, None],
        ]
    )
    table = read_table(content, "c.xlsx", CUSTOMERS)
    assert table.frame["customer_id"].tolist() == ["C1"]
    assert table.row_numbers == [2]


# --------------------------------------------------------------------------- file rejected (E011)


@pytest.mark.parametrize(
    ("header", "fragment"),
    [
        ("customer_id,name", "missing country"),
        ("customer_id,name,country,region", "unexpected region"),
        ("name,customer_id,country", "wrong order"),
        ("Customer_ID,name,country", "missing customer_id; unexpected Customer_ID"),
        ("customer id,name,country", "missing customer_id"),
    ],
)
def test_header_mismatch_rejects_the_file(header: str, fragment: str) -> None:
    with pytest.raises(FileRejectedError) as exc:
        read_table(csv_bytes(header, "C1,Acme,GB"), "c.csv", CUSTOMERS)
    assert exc.value.code == "E011"
    assert fragment in exc.value.message
    assert exc.value.details["expected"] == ["customer_id", "name", "country"]


def test_headers_with_surrounding_spaces_are_accepted() -> None:
    table = read_table(csv_bytes(" customer_id , name,country ", "C1,Acme,GB"), "c.csv", CUSTOMERS)
    assert len(table.frame) == 1


@pytest.mark.parametrize(
    ("content", "filename", "fragment"),
    [
        (b"", "c.csv", "empty"),
        ("customer_id,name,country\r\nC1,Café,FR".encode("cp1252"), "c.csv", "UTF-8"),
        (b"customer_id,name,country\r\nC1,Acme,GB,extra", "c.csv", "beyond the last column"),
        (b"not a workbook", "c.xlsx", "could not be opened"),
        (b"customer_id,name,country", "c.txt", "not a .csv or .xlsx"),
    ],
    ids=["empty", "not utf-8", "extra cell", "broken xlsx", "wrong extension"],
)
def test_unreadable_files_are_rejected(content: bytes, filename: str, fragment: str) -> None:
    with pytest.raises(FileRejectedError) as exc:
        read_table(content, filename, CUSTOMERS)
    assert fragment in exc.value.message


def test_short_rows_are_padded_and_quoted_commas_kept() -> None:
    table = read_table(
        csv_bytes("customer_id,name,country", 'C1,"Acme, Inc."', "C2,Beta,GB"), "c.csv", CUSTOMERS
    )
    assert table.frame.iloc[0].tolist() == ["C1", "Acme, Inc.", ""]


# --------------------------------------------------------------------------- cell types


def test_types_are_parsed() -> None:
    row = only_row(
        csv_bytes(LINE_HEADER, " C1 ,2,P1,1.5,12000.00,800,2025-01-01,2025-12-31 00:00:00,"),
        "lines.csv",
    )
    assert row.ok, row.errors
    assert row.values == {
        "contract_id": "C1",
        "line_no": 2,
        "product_id": "P1",
        "quantity": Decimal("1.5"),
        "unit_price": Decimal("12000.00"),
        "discount": Decimal("800"),
        "service_start": date(2025, 1, 1),
        "service_end": date(2025, 12, 31),
        "completion_date": None,
    }
    assert row.raw["contract_id"] == "C1"  # trimmed


def test_blank_discount_uses_default_zero() -> None:
    row = only_row(csv_bytes(LINE_HEADER, "C1,1,P1,1,10,,2025-01-01,2025-01-31,"), "lines.csv")
    assert row.values["discount"] == Decimal(0)


@pytest.mark.parametrize(
    ("column", "value", "code"),
    [
        ("contract_id", "", "E001"),
        ("line_no", "1.5", "E002"),
        ("line_no", "one", "E002"),
        ("quantity", "1.23456", "E002"),  # more than 4 decimals
        ("unit_price", "10.005", "E002"),  # money: at most 2 decimals (D1)
        ("unit_price", "12,000.00", "E002"),  # thousands separator
        ("unit_price", "NaN", "E002"),
        ("service_start", "31/01/2025", "E003"),
        ("service_start", "2025-02-30", "E003"),
        ("service_start", "2025", "E003"),  # not taken as an Excel serial
        ("service_end", "", "E001"),
    ],
)
def test_bad_cells_get_their_error_code(column: str, value: str, code: str) -> None:
    good = {
        "contract_id": "C1", "line_no": "1", "product_id": "P1", "quantity": "1",
        "unit_price": "10", "discount": "", "service_start": "2025-01-01",
        "service_end": "2025-01-31", "completion_date": "",
    }  # fmt: skip
    good[column] = value
    cells = [f'"{good[h]}"' for h in LINES.headers]
    row = only_row(csv_bytes(LINE_HEADER, ",".join(cells)), "lines.csv")
    assert [(e.column, e.code) for e in row.errors] == [(column, code)]
    assert row.errors[0].raw_value == value
    assert row.errors[0].row_number == 2
    assert column not in row.values


def test_money_trailing_zeros_are_fine() -> None:
    row = only_row(csv_bytes(LINE_HEADER, "C1,1,P1,1,10.500,,2025-01-01,2025-01-31,"), "lines.csv")
    assert row.values["unit_price"] == Decimal("10.5")


def test_choices_and_yes_no_ignore_case() -> None:
    header = ",".join(PRODUCTS.headers)
    row = only_row(
        csv_bytes(header, "P1,Sub,,100,fixed,100,,ratable_daily,y,4100,"), "p.csv", PRODUCTS
    )
    assert row.ok, row.errors
    assert row.values["ssp_source"] == "FIXED"
    assert row.values["recognition_method"] == "RATABLE_DAILY"
    assert row.values["separate_obligation"] is True


def test_text_longer_than_column_is_refused() -> None:
    row = only_row(csv_bytes("customer_id,name,country", "C1,Acme,GBR"), "c.csv", CUSTOMERS)
    assert [(e.column, e.code) for e in row.errors] == [("country", "E002")]


def test_xlsx_numbers_become_plain_text() -> None:
    content = xlsx_bytes(
        [LINES.headers, ["C1", 1.0, "P1", 1, 12.54, 0.1, "2025-01-01", "2025-01-31", None]]
    )
    table = read_table(content, "lines.xlsx", LINES)
    record = table.frame.iloc[0]
    assert (record["line_no"], record["unit_price"], record["discount"]) == ("1", "12.54", "0.1")


# --------------------------------------------------------------------------- real files


@pytest.mark.parametrize("template", list(TEMPLATES.values()), ids=lambda t: t.name.value)
def test_downloaded_templates_parse_cleanly(template) -> None:  # type: ignore[no-untyped-def]
    for content, filename in (
        (template_csv(template).encode(), "t.csv"),
        (template_xlsx(template), "t.xlsx"),
    ):
        rows = parse_rows(read_table(content, filename, template), template)
        assert len(rows) == 1 and rows[0].ok, rows[0].errors


BENCHMARK_INPUTS = sorted((REPO / "benchmarks" / "cases").glob("X0*/inputs/*/*.csv"))


@pytest.mark.parametrize(
    "path", BENCHMARK_INPUTS, ids=lambda p: f"{p.parts[-4][:3]}/{p.parent.name}/{p.name}"
)
def test_benchmark_inputs_parse_without_errors(path: Path) -> None:
    template = get_template(path.stem)
    assert template is not None
    rows = parse_rows(read_table(path.read_bytes(), path.name, template), template)
    assert rows and all(r.ok for r in rows), [e for r in rows for e in r.errors][:3]
