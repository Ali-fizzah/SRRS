"""Every golden case marked ready replays and matches expected/ (plan §11.1 pass rule)."""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy.orm import Session

from tests.benchmarks.runner import CaseResult, case_meta, replay
from tests.integration.conftest import make_user

REPO = Path(__file__).resolve().parents[3]
CASES = REPO / "benchmarks" / "cases"
READY = [p for p in sorted(CASES.iterdir()) if p.is_dir() and case_meta(p)["status"] == "ready"]


def _seed_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("seed", REPO / "tools" / "seed.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


seed = _seed_module()


@pytest.mark.parametrize("case_dir", READY, ids=lambda p: p.name)
def test_golden_case(case_dir: Path, db: Session, results: dict[str, CaseResult]) -> None:
    result = replay(db, case_dir, seed, make_user)
    results[case_dir.name] = result
    worst = sorted(result.failures, key=lambda v: v.difference, reverse=True)[:10]
    assert result.passed, "\n".join(
        [*result.problems[:10], *[f"{v.check} {v.key}: {v.expected} vs {v.actual}" for v in worst]]
    )
