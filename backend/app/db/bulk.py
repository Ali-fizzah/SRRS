"""Bulk writes with PostgreSQL COPY, for the 50,000-line target (plan §4, task P7-T2).

Table and column names come from the models or from constants here, never from user input.
"""

from collections.abc import Iterable, Sequence
from typing import Any

from psycopg.types.json import Jsonb
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.base import Base


def copy_table(db: Session, table: str, columns: list[str], rows: Iterable[Sequence[Any]]) -> int:
    """COPY rows into a table, inside the session's transaction. Returns how many."""
    raw = db.connection().connection.driver_connection
    count = 0
    statement = f"COPY {table} ({', '.join(columns)}) FROM STDIN"
    with raw.cursor() as cursor, cursor.copy(statement) as copy:  # type: ignore[union-attr]
        for row in rows:
            copy.write_row([Jsonb(v) if isinstance(v, dict) else v for v in row])
            count += 1
    return count


def copy_rows(
    db: Session, model: type[Base], columns: list[str], rows: Iterable[Sequence[Any]]
) -> int:
    return copy_table(db, model.__tablename__, columns, rows)


def reserve_ids(db: Session, model: type[Base], count: int) -> list[int]:
    """Take ids from the table's sequence, so related rows can be written before the insert."""
    if count == 0:
        return []
    return list(
        db.scalars(
            text(f"SELECT nextval('{model.__tablename__}_id_seq') FROM generate_series(1, :count)"),
            {"count": count},
        )
    )


def analyze(db: Session, *models: type[Base]) -> None:
    """Refresh planner statistics after a bulk write. Without them PostgreSQL can pick a plan that
    takes minutes instead of milliseconds on the next query (found by task P6-T3)."""
    names = ", ".join(model.__tablename__ for model in models)
    db.execute(text(f"ANALYZE {names}"))
