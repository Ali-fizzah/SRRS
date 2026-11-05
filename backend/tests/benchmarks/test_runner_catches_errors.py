"""The replay must FAIL on a wrong expected value, or a green benchmark would prove nothing."""

import importlib.util
import shutil
import sys
from decimal import Decimal
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy.orm import Session

from tests.benchmarks.runner import replay
from tests.integration.conftest import make_user

REPO = Path(__file__).resolve().parents[3]
U01 = REPO / "benchmarks" / "cases" / "U01_ratable_monthly_12m"
B01 = REPO / "benchmarks" / "cases" / "B01_worked_example"


def _seed_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("seed", REPO / "tools" / "seed.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


seed = _seed_module()


def tampered(tmp_path: Path, source: Path, file: str, old: str, new: str) -> Path:
    """A copy of a case with one expected value changed (the real files are never touched)."""
    case = tmp_path / source.name
    shutil.copytree(source, case)
    path = case / "expected" / file
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")
    return case


@pytest.mark.parametrize(
    ("source", "file", "old", "new", "check"),
    [
        (U01, "schedule.csv", "202503,100.00", "202503,100.02", "schedule"),
        (U01, "allocation.csv", "1200.00", "1200.05", "allocation"),
        (
            U01,
            "postings.csv",
            "202503,U01,1,REVENUE,100.00",
            "202503,U01,1,REVENUE,99.00",
            "postings",
        ),
        (B01, "balances.csv", "10266.67", "10266.70", "balances"),
    ],
    ids=["schedule", "allocation", "postings", "balances"],
)
def test_a_wrong_expected_value_fails_the_case(
    db: Session, tmp_path: Path, source: Path, file: str, old: str, new: str, check: str
) -> None:
    result = replay(db, tampered(tmp_path, source, file, old, new), seed, make_user)
    assert not result.passed
    assert {v.check for v in result.failures} == {check}


def test_a_line_missing_from_expected_fails_the_case(db: Session, tmp_path: Path) -> None:
    result = replay(
        db, tampered(tmp_path, U01, "schedule.csv", "U01,1,202503,100.00\n", ""), seed, make_user
    )
    assert [v.key for v in result.failures] == ["U01/1/202503"]


def test_exactly_the_tolerance_passes_and_just_over_fails(db: Session, tmp_path: Path) -> None:
    """§11.1: within 0.01."""
    at_limit = replay(
        db,
        tampered(tmp_path, U01, "schedule.csv", "202503,100.00", "202503,100.01"),
        seed,
        make_user,
    )
    assert at_limit.passed
    assert at_limit.max_variance == Decimal("0.01")


def test_just_over_the_tolerance_fails(db: Session, tmp_path: Path) -> None:
    result = replay(
        db,
        tampered(tmp_path, U01, "schedule.csv", "202503,100.00", "202503,100.0101"),
        seed,
        make_user,
    )
    assert not result.passed
