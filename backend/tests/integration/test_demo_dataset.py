"""P2-T6: the FYP-I demo dataset gives exactly what docs/demo-fyp1.md tells the audience."""

import importlib.util
import sys
from decimal import Decimal
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.roles import Role
from app.ingestion.loader import load_upload
from app.ingestion.parser import detect_template
from app.models import (
    Contract,
    ContractVersion,
    PerformanceObligation,
    RevenueSchedule,
    ScheduleLine,
    UploadFile,
    ValidationError,
)
from app.services.recognition_run import run_recognition
from tests.integration.conftest import make_user

REPO = Path(__file__).resolve().parents[3]
DATA = REPO / "docs" / "demo-fyp1" / "data"


def _seed_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("seed", REPO / "tools" / "seed.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def upload(db: Session, user_id: int, *names: str) -> dict[str, tuple[str, int, int, int]]:
    """Upload files exactly as the page does: the template comes from each file's header row."""
    batch = []
    for name in names:
        content = (DATA / name).read_bytes()
        template = detect_template(content, name)
        assert template is not None, name
        record = UploadFile(
            template=template,
            original_filename=name,
            sha256="0" * 64,
            stored_path="(test)",
            uploaded_by=user_id,
            period_key="202612",
        )
        db.add(record)
        batch.append((record, content))
    db.flush()
    return {
        name: (s.status.value, s.total_rows, s.accepted_rows, s.rejected_rows)
        for name, s in zip(names, load_upload(db, batch, user_id), strict=True)
    }


def errors(db: Session, filename: str) -> list[tuple[int, str]]:
    return [
        tuple(row)  # type: ignore[misc]
        for row in db.execute(
            select(ValidationError.row_number, ValidationError.error_code)
            .join(UploadFile, UploadFile.id == ValidationError.upload_file_id)
            .where(UploadFile.original_filename == filename)
            .order_by(ValidationError.row_number)
        )
    ]


def schedule_of(db: Session, code: str) -> list[Decimal]:
    return list(
        db.scalars(
            select(ScheduleLine.amount)
            .join(RevenueSchedule, RevenueSchedule.id == ScheduleLine.schedule_id)
            .join(ContractVersion, ContractVersion.id == RevenueSchedule.contract_version_id)
            .join(Contract, Contract.id == ContractVersion.contract_id)
            .where(Contract.contract_code == code)
            .order_by(ScheduleLine.service_period)
        )
    )


@pytest.fixture
def user_id(db: Session) -> int:
    seed = _seed_module()
    seed.seed_accounts(db)
    seed.seed_periods(db, "202612")
    return make_user(db, [Role.ADMIN]).id


GOOD = ("customers.csv", "products.csv", "contracts.csv", "contract_lines.csv")
BAD = ("bad_contracts.csv", "bad_contract_lines.csv")


def test_step_1_the_good_files_are_all_accepted(db: Session, user_id: int) -> None:
    assert upload(db, user_id, *GOOD) == {
        "customers.csv": ("ACCEPTED", 4, 4, 0),
        "products.csv": ("ACCEPTED", 4, 4, 0),
        "contracts.csv": ("ACCEPTED", 4, 4, 0),
        "contract_lines.csv": ("ACCEPTED", 5, 5, 0),
    }


def test_step_2_the_bad_upload_loads_one_contract_and_explains_the_rest(
    db: Session, user_id: int
) -> None:
    upload(db, user_id, *GOOD)
    assert upload(db, user_id, *BAD) == {
        "bad_contracts.csv": ("PARTIAL", 3, 1, 2),
        "bad_contract_lines.csv": ("PARTIAL", 3, 1, 2),
    }
    # 000201: the line starts on the 15th (E012), so its contract row is held back (E013).
    # 000202: the customer does not exist (E004), so its line is held back (E013).
    assert errors(db, "bad_contracts.csv") == [(3, "E013"), (4, "E004")]
    assert errors(db, "bad_contract_lines.csv") == [(3, "E012"), (4, "E013")]
    assert set(db.scalars(select(Contract.contract_code))) == {
        "000101-SUB", "000102-SUB", "000103-SUB", "000104-SUB", "000105-SUB",
    }  # fmt: skip


def test_step_3_recognition_gives_the_numbers_in_the_walkthrough(db: Session, user_id: int) -> None:
    upload(db, user_id, *GOOD)
    upload(db, user_id, *BAD)
    summary = run_recognition(db, user_id)
    assert summary.skipped == []
    assert (summary.contracts_generated, summary.obligations_created) == (5, 5)
    assert summary.schedule_lines_created == 72

    assert schedule_of(db, "000101-SUB") == [Decimal("100.00")] * 12
    assert schedule_of(db, "000102-SUB") == [Decimal("933.33")] * 11 + [Decimal("933.37")]
    # 5 x 1,200.00 - 600.00 discount = 5,400.00
    assert schedule_of(db, "000103-SUB") == [Decimal("450.00")] * 12
    # 1,200.00 + 500.00 setup fee = 1,700.00; the fee gets no obligation of its own (D4)
    assert schedule_of(db, "000104-SUB") == [Decimal("141.67")] * 11 + [Decimal("141.63")]
    assert schedule_of(db, "000105-SUB") == [Decimal("1000.00")] * 24

    allocated = db.scalar(select(func.sum(PerformanceObligation.allocated_amount)))
    scheduled = db.scalar(select(func.sum(ScheduleLine.amount)))
    assert allocated == scheduled == Decimal("43500.00")
