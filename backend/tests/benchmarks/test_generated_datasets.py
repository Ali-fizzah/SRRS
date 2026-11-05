"""P6-T1, P6-T3: seeded datasets through real ingestion, engine, journals and close.

Run order from the plan: single contracts -> bundles -> events -> everything together. Each
generated case carries expected values worked out without the engine.
"""

import importlib.util
import os
import sys
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy.orm import Session

from tests.benchmarks.runner import CaseResult, replay
from tests.benchmarks.test_golden_cases import seed
from tests.integration.conftest import make_user

REPO = Path(__file__).resolve().parents[3]


def _generator() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "generate_dataset", REPO / "tools" / "generate_dataset.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


generator = _generator()
STRESS = os.environ.get("REVREC_STRESS", "")  # "<seeds>:<lines>", set by make stress


def _replay(db: Session, tmp_path: Path, profile: str, seed_no: int, lines: int) -> CaseResult:
    case = tmp_path / f"G_{profile}_s{seed_no}"
    generator.generate(case, lines, seed_no, profile)
    return replay(db, case, seed, make_user)


@pytest.mark.parametrize(
    ("profile", "seed_no", "lines"),
    [
        ("single", 1, 80),
        ("bundles", 2, 80),
        ("events", 3, 80),
        ("full", 4, 120),
    ],
    ids=["1-single", "2-bundles", "3-events", "4-full"],
)
def test_generated_dataset_matches_its_independent_expected_values(
    db: Session,
    tmp_path: Path,
    results: dict[str, CaseResult],
    profile: str,
    seed_no: int,
    lines: int,
) -> None:
    result = _replay(db, tmp_path, profile, seed_no, lines)
    results[result.case] = result
    worst = sorted(result.failures, key=lambda v: v.difference, reverse=True)[:12]
    assert result.passed, "\n".join(
        [*result.problems[:12], *[f"{v.check} {v.key}: {v.expected} vs {v.actual}" for v in worst]]
    )


@pytest.mark.skipif(not STRESS, reason="make stress S=<seeds> N=<lines>")
@pytest.mark.parametrize("profile", ["single", "bundles", "events", "full"])
@pytest.mark.parametrize(
    "seed_no", range(100, 100 + int(STRESS.split(":")[0] or 0)) if STRESS else [0]
)
def test_stress(
    db: Session,
    tmp_path: Path,
    results: dict[str, CaseResult],
    profile: str,
    seed_no: int,
) -> None:
    """Hunting for bugs: more seeds and more lines than `make bench` can afford (P6-T3)."""
    result = _replay(db, tmp_path, profile, seed_no, int(STRESS.split(":")[1]))
    results[result.case] = result
    worst = sorted(result.failures, key=lambda v: v.difference, reverse=True)[:8]
    assert result.passed, "\n".join(
        [*result.problems[:8], *[f"{v.check} {v.key}: {v.expected} vs {v.actual}" for v in worst]]
    )


def test_the_same_seed_gives_the_same_files(tmp_path: Path) -> None:
    generator.generate(tmp_path / "a", 60, 9, "full")
    generator.generate(tmp_path / "b", 60, 9, "full")
    files_a = sorted(p.relative_to(tmp_path / "a") for p in (tmp_path / "a").rglob("*.csv"))
    files_b = sorted(p.relative_to(tmp_path / "b") for p in (tmp_path / "b").rglob("*.csv"))
    assert files_a == files_b
    for name in files_a:
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes()


def test_the_full_profile_covers_what_the_plan_lists(tmp_path: Path) -> None:
    """P6-T1: staggered starts, bundles, deliveries, events, invoices, credit notes."""
    stats = generator.generate(tmp_path / "c", 400, 11, "full")
    for kind in (
        "invoices",
        "deliveries",
        "credit_notes",
        "renewals",
        "cancellations",
        "upgrades",
        "late_invoices",
    ):
        assert stats.get(kind, 0) > 0, kind
    assert stats["lines"] > stats["contracts"]  # bundles
