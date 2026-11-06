"""P1-T1: schema rules from plan §6 checked on the model metadata (no database)."""

import pytest
from sqlalchemy import Float, Numeric, Table

import app.models  # noqa: F401  (registers every table)
from app.db.base import Base

TABLES = Base.metadata.tables

# Plan §6.1, every table.
EXPECTED_TABLES = {
    "customers", "products", "ssp_rules", "gl_accounts", "gl_mappings",
    "contracts", "contract_versions", "contract_lines", "performance_obligations", "deliveries",
    "invoices", "invoice_lines", "credit_notes",
    "revenue_schedules", "schedule_lines",
    "accounting_periods", "journal_batches", "journal_entries", "journal_lines",
    "upload_files", "validation_errors", "job_runs", "audit_log", "users", "roles", "user_roles",
}  # fmt: skip

# Tables loaded from uploaded files keep src columns (CLAUDE.md rule 5).
IMPORTED_TABLES = {
    "customers", "products", "ssp_rules", "contract_versions", "contract_lines", "deliveries",
    "invoices", "invoice_lines", "credit_notes",
}  # fmt: skip

MONEY_COLUMNS = {
    "products": ["list_price"],
    "ssp_rules": ["ssp_value"],
    "contract_versions": ["transaction_price"],
    "contract_lines": ["unit_price", "discount", "net_price"],
    "performance_obligations": ["ssp_amount", "allocated_amount"],
    "invoices": ["total_amount"],
    "invoice_lines": ["amount"],
    "credit_notes": ["amount"],
    "schedule_lines": ["amount"],
    "journal_batches": ["total_debit", "total_credit"],
    "journal_lines": ["debit", "credit"],
}


def test_every_planned_table_exists() -> None:
    assert set(TABLES) == EXPECTED_TABLES


@pytest.mark.parametrize("table", sorted(EXPECTED_TABLES))
def test_id_and_created_at(table: str) -> None:
    t: Table = TABLES[table]
    assert [c.name for c in t.primary_key.columns] == ["id"]
    assert not t.c.created_at.nullable


@pytest.mark.parametrize("table", sorted(IMPORTED_TABLES))
def test_imported_tables_keep_source(table: str) -> None:
    t = TABLES[table]
    for name in ("source_upload_id", "source_row", "source_payload"):
        assert name in t.c, f"{table}.{name}"
    fks = {fk.target_fullname for fk in t.c.source_upload_id.foreign_keys}
    assert fks == {"upload_files.id"}


def test_money_columns_are_numeric_18_2() -> None:
    for table, columns in MONEY_COLUMNS.items():
        for name in columns:
            col_type = TABLES[table].c[name].type
            assert isinstance(col_type, Numeric), f"{table}.{name}"
            assert (col_type.precision, col_type.scale) == (18, 2), f"{table}.{name}"


def test_no_float_columns_anywhere() -> None:
    """D1: never float for money; no column needs float at all."""
    for t in TABLES.values():
        for c in t.columns:
            assert not isinstance(c.type, Float), f"{t.name}.{c.name}"


def test_every_foreign_key_is_indexed() -> None:
    """Plan §6.2: index all FKs (PostgreSQL does not do it automatically)."""
    for t in TABLES.values():
        indexed = {idx.columns[0].name for idx in t.indexes}
        for c in t.columns:
            if c.foreign_keys:
                assert c.name in indexed, f"{t.name}.{c.name}"


def test_journal_entries_trace_back_to_source() -> None:
    """Plan §5.7: contract, version, source document and source upload + row."""
    c = TABLES["journal_entries"].c
    for name in ("contract_id", "contract_version_id", "source_type", "source_id"):
        assert name in c
    assert "source_upload_id" in c and "source_row" in c
