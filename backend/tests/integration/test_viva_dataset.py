"""P8-T2: the viva dataset gives exactly what docs/demo-viva.md tells the examiners.

The expected figures here were worked out by hand from plan §5, and are shown in the document, so
`make test` fails if later work changes what the demo shows.
"""

import importlib.util
import sys
from decimal import Decimal
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.passwords import password_problem
from app.auth.roles import Role
from app.db.base import Base
from app.ingestion.loader import load_upload
from app.ingestion.parser import detect_template
from app.models import (
    AccountingPeriod,
    Contract,
    ContractVersion,
    JournalBatch,
    JournalEntry,
    PerformanceObligation,
    UploadFile,
    ValidationError,
)
from app.models.enums import ObligationStatus, PeriodStatus
from app.services.billing import balance_at, contract_balances
from app.services.journals import approve_batch, generate_journals, post_batch
from app.services.period_close import (
    build_checklist,
    close_period,
    gl_balances,
    start_close,
    sub_ledger_balances,
)
from app.services.recognition_run import run_recognition
from tests.integration.conftest import make_user

REPO = Path(__file__).resolve().parents[3]
DATA = REPO / "docs" / "demo-viva" / "data"
D = Decimal


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, REPO / "tools" / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


seed = _load("seed")
seed_demo_users = _load("seed_demo_users")


def upload(db: Session, user_id: int, period: str, folder: str) -> dict[str, tuple[str, int]]:
    """Upload a folder as the page does: each file's template comes from its header row."""
    batch = []
    for path in sorted((DATA / folder).glob("*.csv")):
        content = path.read_bytes()
        template = detect_template(content, path.name)
        assert template is not None, path.name
        record = UploadFile(
            template=template,
            original_filename=path.name,
            sha256="0" * 64,
            stored_path="(test)",
            uploaded_by=user_id,
            period_key=period,
        )
        db.add(record)
        batch.append((record, content))
    db.flush()
    summaries = load_upload(db, batch, user_id)
    return {
        record.original_filename: (summary.status.value, summary.accepted_rows)
        for (record, _), summary in zip(batch, summaries, strict=True)
    }


def balances(db: Session, code: str, period: str) -> tuple[int, int]:
    contract_id = db.scalar(select(Contract.id).where(Contract.contract_code == code))
    assert contract_id is not None
    return balance_at(contract_balances(db, contract_id), period)


def allocated(db: Session, code: str, version_no: int) -> list[Decimal]:
    return list(
        db.scalars(
            select(PerformanceObligation.allocated_amount)
            .join(ContractVersion, ContractVersion.id == PerformanceObligation.contract_version_id)
            .join(Contract, Contract.id == ContractVersion.contract_id)
            .where(Contract.contract_code == code, ContractVersion.version_no == version_no)
            .order_by(PerformanceObligation.contract_line_id)
        )
    )


def book(db: Session, period: str, accountant: int, approver: int) -> tuple[str, int]:
    """Generate, approve and post, as the script does. Returns (debits, entries)."""
    summary = generate_journals(db, period, accountant)
    assert summary.skipped == []
    assert summary.batch_id is not None
    approve_batch(db, summary.batch_id, approver)
    post_batch(db, summary.batch_id, approver)
    return summary.total_debit, summary.entries


@pytest.fixture
def users(db: Session) -> tuple[int, int]:
    seed.seed_accounts(db)
    seed.seed_gl_mappings(db)
    seed.seed_periods(db, "202705")
    return (make_user(db, [Role.ACCOUNTANT]).id, make_user(db, [Role.APPROVER]).id)


def test_may_upload_and_its_errors(db: Session, users: tuple[int, int]) -> None:
    accountant, _ = users
    good = upload(db, accountant, "202705", "may")
    assert {status for status, _ in good.values()} == {"ACCEPTED"}
    assert len(good) == 5

    bad = upload(db, accountant, "202705", "may-with-errors")
    assert bad == {"contract_lines.csv": ("PARTIAL", 1), "contracts.csv": ("PARTIAL", 1)}
    codes = dict(
        db.execute(
            select(ValidationError.error_code, func.count())
            .where(ValidationError.error_code.in_(["E004", "E012", "E013"]))
            .group_by(ValidationError.error_code)
        )
        .tuples()
        .all()
    )
    assert codes == {"E004": 1, "E012": 1, "E013": 2}
    held_back = db.scalars(select(Contract.contract_code).order_by(Contract.contract_code)).all()
    assert list(held_back) == ["V-1001", "V-1002", "V-1003", "V-1004", "V-1005"]


def _through_may(db: Session, users: tuple[int, int]) -> None:
    accountant, approver = users
    upload(db, accountant, "202705", "may")
    upload(db, accountant, "202705", "may-with-errors")
    summary = run_recognition(db, accountant, period_key="202705")
    assert summary.skipped == []
    assert summary.contracts_generated == 5
    assert book(db, "202705", accountant, approver) == ("23768.32", 10)


def test_may_figures(db: Session, users: tuple[int, int]) -> None:
    _through_may(db, users)
    assert allocated(db, "V-1001", 1) == [D("11200.00"), D("1400.00")]  # the proposal's example
    assert balances(db, "V-1001", "202705") == (653335, 0)
    assert balances(db, "V-1002", "202705") == (110000, 0)
    assert balances(db, "V-1003", "202705") == (0, 151000)  # no invoice yet: unbilled
    assert balances(db, "V-1004", "202705") == (155833, 0)
    assert balances(db, "V-1005", "202705") == (0, 45000)
    assert gl_balances(db, "202705") == (919168, 196000)
    assert sub_ledger_balances(db, "202705") == (919168, 196000)


def test_june_figures_after_the_cancellation_and_the_upgrade(
    db: Session, users: tuple[int, int]
) -> None:
    accountant, approver = users
    _through_may(db, users)
    assert not build_checklist(db, "202705").blocking
    start_close(db, "202705", accountant)
    close_period(db, "202705", approver)

    june = upload(db, accountant, "202706", "june")
    assert {status for status, _ in june.values()} == {"ACCEPTED"}
    summary = run_recognition(db, accountant, period_key="202706")
    assert summary.events_applied == 2 and summary.skipped == []

    # §5.5, D8: 2,000.00 left + 800.00 added, shared 2,000 : 1,000.
    assert allocated(db, "V-1003", 2) == [D("1866.67"), D("933.33")]
    assert book(db, "202706", accountant, approver) == ("4989.00", 7)

    assert balances(db, "V-1001", "202706") == (560002, 0)
    assert balances(db, "V-1002", "202706") == (0, 0)  # cancelled, credit note took the rest
    assert balances(db, "V-1003", "202706") == (12600, 0)  # invoice cleared unbilled first
    assert balances(db, "V-1004", "202706") == (141666, 0)
    assert balances(db, "V-1005", "202706") == (0, 90000)
    assert gl_balances(db, "202706") == (714268, 90000)
    assert sub_ledger_balances(db, "202706") == (714268, 90000)

    start_close(db, "202706", accountant)
    checklist = build_checklist(db, "202706")
    assert not checklist.blocking
    assert next(i for i in checklist.items if i.id == "warnings").status == "pass"
    close_period(db, "202706", approver)
    open_period = db.scalar(
        select(AccountingPeriod.period_key).where(AccountingPeriod.status == PeriodStatus.OPEN)
    )
    assert open_period == "202707"

    assert db.scalar(select(func.count()).select_from(JournalBatch)) == 2
    credit_notes = db.scalar(
        select(func.count())
        .select_from(JournalEntry)
        .where(JournalEntry.entry_type == "CREDIT_NOTE")
    )
    assert credit_notes == 1
    cancelled = db.scalar(select(Contract.status).where(Contract.contract_code == "V-1002"))
    assert cancelled == "CANCELLED"
    statuses = set(
        db.scalars(
            select(PerformanceObligation.status)
            .join(ContractVersion, ContractVersion.id == PerformanceObligation.contract_version_id)
            .join(Contract, Contract.id == ContractVersion.contract_id)
            .where(Contract.contract_code == "V-1002")
        )
    )
    assert statuses == {ObligationStatus.SUPERSEDED}


def test_demo_users_are_created_once_and_meet_the_password_policy(db: Session) -> None:
    assert len(seed_demo_users.seed_demo_users(db)) == 2
    assert seed_demo_users.seed_demo_users(db) == []
    for _, _, password, _ in seed_demo_users.DEMO_USERS:
        assert password_problem(password) is None


def test_the_archived_schema_has_every_table_and_trigger() -> None:
    """P8-T1. Fails if a migration was added without running `make release-archive`."""
    schema = (REPO / "docs" / "release" / "schema.sql").read_text(encoding="utf-8")
    for table in Base.metadata.sorted_tables:
        assert f"CREATE TABLE public.{table.name} " in schema, table.name
    for trigger in ("trg_journal_lines_guard", "trg_audit_log_append_only"):
        assert trigger in schema
    assert "uq_journal_entries_one_per_document" in schema
