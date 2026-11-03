"""Upload parser (plan §7, task P1-T6).

Two steps:
1. `read_table`: CSV or XLSX bytes -> every cell as a trimmed string, headers checked
   against the template. Any file-level problem raises `FileRejectedError` (E011).
2. `parse_rows`: each string checked against its column type -> typed values or
   cell errors E001 (missing), E002 (wrong type), E003 (invalid date).

Business rules (references, duplicates, negatives, date ranges) are the validators
of task P1-T7.
"""

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

import pandas as pd

from app.ingestion.templates import Column, ColumnType, Template

# --------------------------------------------------------------------------- errors


class FileRejectedError(Exception):
    """The whole file is refused (E011); no row is loaded."""

    code = "E011"

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


@dataclass(frozen=True)
class CellError:
    row_number: int
    column: str
    code: str  # E001 / E002 / E003
    message: str
    raw_value: str


# --------------------------------------------------------------------------- step 1: read


@dataclass(frozen=True)
class RawTable:
    """Every cell as a string. `row_numbers[i]` is the file row of `frame` row i
    (the header is row 1, so the first data row is row 2)."""

    frame: pd.DataFrame
    row_numbers: list[int]


def read_table(content: bytes, filename: str, template: Template) -> RawTable:
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if extension == "csv":
        rows = _csv_rows(content)
    elif extension == "xlsx":
        rows = _xlsx_rows(content)
    else:
        raise FileRejectedError(
            f"{filename!r} is not a .csv or .xlsx file.", {"accepted": [".csv", ".xlsx"]}
        )
    if not rows:
        raise FileRejectedError("The file is empty: the first row must hold the column headers.")

    _, header = rows[0]
    _check_headers(_trim_trailing_blanks(header), template)
    width = len(template.headers)

    data: list[list[str]] = []
    numbers: list[int] = []
    for number, cells in rows[1:]:
        if len(cells) > width and any(c for c in cells[width:]):
            raise FileRejectedError(
                f"Row {number} has values beyond the last column ({template.headers[-1]}).",
                {"row_number": number},
            )
        cells = (cells + [""] * width)[:width]
        if all(c == "" for c in cells):
            continue  # blank row (often trailing): skipped, numbering kept
        data.append(cells)
        numbers.append(number)
    frame = pd.DataFrame(data, columns=template.headers, dtype=str)
    return RawTable(frame=frame, row_numbers=numbers)


def _csv_rows(content: bytes) -> list[tuple[int, list[str]]]:
    try:
        text = content.decode("utf-8-sig")  # drops a leading BOM (Excel "CSV UTF-8")
    except UnicodeDecodeError as exc:
        raise FileRejectedError(
            "The file is not UTF-8 text. In Excel use Save As > 'CSV UTF-8 (Comma delimited)'.",
            {"byte_offset": exc.start},
        ) from exc
    try:
        records = list(csv.reader(io.StringIO(text, newline="")))
    except csv.Error as exc:
        raise FileRejectedError(f"The CSV file could not be read: {exc}.") from exc
    return [(i, [cell.strip() for cell in record]) for i, record in enumerate(records, start=1)]


def _xlsx_rows(content: bytes) -> list[tuple[int, list[str]]]:
    from openpyxl import load_workbook

    try:
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception as exc:  # openpyxl raises several unrelated types for bad files
        raise FileRejectedError("The file could not be opened as an Excel .xlsx workbook.") from exc
    try:
        sheet = workbook.worksheets[0]  # §7: first sheet
        return [
            (number, [_xlsx_cell(v) for v in values])
            for number, values in enumerate(sheet.iter_rows(values_only=True), start=1)
        ]
    finally:
        workbook.close()


def _xlsx_cell(value: Any) -> str:
    """Excel cell -> the text a person would read."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, datetime):
        if value.time() == datetime.min.time():
            return value.date().isoformat()
        return value.isoformat(sep=" ")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return repr(value)  # shortest form that round-trips: 12.54, not 12.539999...
    return str(value).strip()


def _trim_trailing_blanks(header: list[str]) -> list[str]:
    end = len(header)
    while end and header[end - 1] == "":
        end -= 1
    return header[:end]


def _check_headers(found: list[str], template: Template) -> None:
    expected = template.headers
    if found == expected:
        return
    missing = [h for h in expected if h not in found]
    unexpected = [h for h in found if h not in expected]
    details: dict[str, Any] = {"expected": expected, "found": found}
    if missing:
        details["missing"] = missing
    if unexpected:
        details["unexpected"] = unexpected
    if not missing and not unexpected:
        problem = "the columns are in the wrong order"
    else:
        parts = []
        if missing:
            parts.append("missing " + ", ".join(missing))
        if unexpected:
            parts.append("unexpected " + ", ".join(unexpected))
        problem = "; ".join(parts)
    raise FileRejectedError(
        f"The headers do not match the {template.name.value} template: {problem}. "
        "Download the template and keep its first row exactly as it is.",
        details,
    )


# --------------------------------------------------------------------------- step 2: types


@dataclass
class ParsedRow:
    row_number: int
    raw: dict[str, str]  # what the file said (kept as source_payload)
    values: dict[str, Any] = field(default_factory=dict)  # typed; absent when the cell failed
    errors: list[CellError] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def parse_rows(table: RawTable, template: Template) -> list[ParsedRow]:
    rows = []
    for number, record in zip(table.row_numbers, table.frame.to_dict("records"), strict=True):
        raw = {str(k): str(v) for k, v in record.items()}
        row = ParsedRow(row_number=number, raw=raw)
        for column in template.columns:
            try:
                row.values[column.name] = parse_value(column, raw[column.name])
            except CellValueError as problem:
                row.errors.append(
                    CellError(number, column.name, problem.code, problem.message, raw[column.name])
                )
        rows.append(row)
    return rows


class CellValueError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def parse_value(column: Column, raw: str) -> Any:
    """One cell -> its typed value (None for a blank optional cell without default)."""
    if raw == "":
        if column.default is not None:
            raw = column.default
        elif column.required:
            raise CellValueError("E001", f"{column.name} is required.")
        else:
            return None
    parse = _PARSERS[column.type]
    return parse(column, raw)


def _text(column: Column, raw: str) -> str:
    if column.max_length is not None and len(raw) > column.max_length:
        raise CellValueError(
            "E002", f"{column.name} is longer than {column.max_length} characters."
        )
    return raw


def _integer(column: Column, raw: str) -> int:
    if not re.fullmatch(r"[+-]?\d+", raw):
        raise CellValueError("E002", f"{column.name} must be a whole number.")
    return int(raw)


def _decimal(column: Column, raw: str) -> Decimal:
    if "," in raw:
        raise CellValueError(
            "E002", f"{column.name} must be a plain number without thousands separators."
        )
    try:
        number = Decimal(raw)
    except InvalidOperation:
        raise CellValueError("E002", f"{column.name} must be a number.") from None
    if not number.is_finite():
        raise CellValueError("E002", f"{column.name} must be a number.")
    # Trailing zeros do not count: 1.500 is 1.5.
    exponent = number.normalize().as_tuple().exponent
    places = -exponent if isinstance(exponent, int) and exponent < 0 else 0
    if column.scale is not None and places > column.scale:
        raise CellValueError("E002", f"{column.name} has more than {column.scale} decimal places.")
    return number


def _choice(column: Column, raw: str) -> str:
    for choice in column.choices:
        if raw.upper() == choice.upper():
            return choice
    raise CellValueError("E002", f"{column.name} must be one of {', '.join(column.choices)}.")


def _yes_no(column: Column, raw: str) -> bool:
    if raw.upper() in ("Y", "N"):
        return raw.upper() == "Y"
    raise CellValueError("E002", f"{column.name} must be Y or N.")


# Excel's day 0 is 1899-12-30 (its calendar wrongly counts 1900-02-29). Serial numbers
# are accepted only between 1970-01-01 and 2099-12-31, so a stray "2025" is not
# silently read as a date in 1905.
_EXCEL_EPOCH = date(1899, 12, 30)
_SERIAL_MIN, _SERIAL_MAX = 25569, 73050


def _date(column: Column, raw: str) -> date:
    text = raw
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}[ T]00:00(:00(\.0+)?)?", text):
        text = text[:10]  # a date-time at midnight, as some exports write dates
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        try:
            return date.fromisoformat(text)
        except ValueError:
            raise CellValueError("E003", f"{column.name}: {raw} is not a real date.") from None
    if re.fullmatch(r"\d+(\.0+)?", text):
        serial = int(text.split(".")[0])
        if _SERIAL_MIN <= serial <= _SERIAL_MAX:
            return _EXCEL_EPOCH + timedelta(days=serial)
    raise CellValueError("E003", f"{column.name} must be a date written as YYYY-MM-DD.")


_PARSERS = {
    ColumnType.TEXT: _text,
    ColumnType.INTEGER: _integer,
    ColumnType.DECIMAL: _decimal,
    ColumnType.MONEY: _decimal,
    ColumnType.DATE: _date,
    ColumnType.CHOICE: _choice,
    ColumnType.YES_NO: _yes_no,
}
