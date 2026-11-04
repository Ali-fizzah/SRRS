"""Shared behaviour of list endpoints (plan §8): paging, sorting and CSV export."""

import csv
import io
import re
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from fastapi import Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.api.errors import ApiError


@dataclass(frozen=True)
class ListParams:
    page: int
    page_size: int
    sort: str | None
    format: Literal["json", "csv"]


def _list_params(
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
    sort: Annotated[str | None, Query(description="Column name; prefix - for descending.")] = None,
    format: Annotated[Literal["json", "csv"], Query()] = "json",
) -> ListParams:
    return ListParams(page, page_size, sort, format)


Listing = Annotated[ListParams, Depends(_list_params)]


def apply_sort(
    statement: Select[Any],
    sort: str | None,
    allowed: Mapping[str, Any],
    default: Sequence[Any],
) -> Select[Any]:
    """ORDER BY a whitelisted column; user input never reaches the SQL (CLAUDE.md rule 8).
    `default` is always appended, so paging stays stable when values repeat."""
    if sort is None:
        return statement.order_by(*default)
    descending = sort.startswith("-")
    name = sort.removeprefix("-")
    column = allowed.get(name)
    if column is None:
        raise ApiError(
            422, "INVALID_SORT", f"Cannot sort by {name!r}.", {"allowed": sorted(allowed)}
        )
    return statement.order_by(column.desc() if descending else column.asc(), *default)


def page_of(db: Session, statement: Select[Any], params: ListParams) -> tuple[list[Any], int]:
    """One page of rows plus the total count of the unpaged query."""
    total = db.scalar(select(func.count()).select_from(statement.order_by(None).subquery())) or 0
    rows = db.execute(
        statement.offset((params.page - 1) * params.page_size).limit(params.page_size)
    ).all()
    return list(rows), total


_FORMULA_START = ("=", "+", "@", "\t", "\r")
_NUMBER = re.compile(r"^[+-]?\d+(\.\d+)?$")


def csv_safe(value: Any) -> Any:
    """Stop Excel running uploaded text as a formula: prefix such cells with an apostrophe."""
    if not isinstance(value, str) or _NUMBER.match(value):
        return value
    if value.startswith((*_FORMULA_START, "-")):
        return "'" + value
    return value


def csv_response(
    filename: str, header: list[str], rows: Iterable[Iterable[Any]]
) -> StreamingResponse:
    """Stream rows as a CSV download, however many there are (plan §4, §8)."""

    def generate() -> Iterator[str]:
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\r\n")
        writer.writerow(header)
        for row in rows:
            writer.writerow(csv_safe(value) for value in row)
            if buffer.tell() > 64 * 1024:
                yield buffer.getvalue()
                buffer.seek(0)
                buffer.truncate()
        yield buffer.getvalue()

    return StreamingResponse(
        generate(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
