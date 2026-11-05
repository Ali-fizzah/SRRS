"""Benchmark fixtures and the per-case table `make bench` prints (plan §11, task P3-T7)."""

import csv
from pathlib import Path
from typing import Any

import pytest

from tests.benchmarks.runner import CaseResult, case_meta
from tests.integration.conftest import (  # noqa: F401  (fixtures used by the replay)
    alembic_config,
    conn,
    db,
    migrated_engine,
    test_db_url,
)

CASES = Path(__file__).resolve().parents[3] / "benchmarks" / "cases"
REPORT = CASES.parent / "reports" / "variance.csv"

RESULTS: dict[str, CaseResult] = {}


def pytest_terminal_summary(terminalreporter: Any) -> None:
    write = terminalreporter.write_line
    folders = sorted(p for p in CASES.iterdir() if p.is_dir())
    write("")
    write(f"{'Case':<34}{'Result':<9}{'Compared':>9}{'Max variance':>14}{'Over tol.':>11}")
    for folder in folders:
        result = RESULTS.get(folder.name)
        if result is None:
            status = "stub" if case_meta(folder)["status"] == "stub" else "not run"
            write(f"{folder.name:<34}{status:<9}")
            continue
        write(
            f"{folder.name:<34}{'PASS' if result.passed else 'FAIL':<9}{result.compared:>9}"
            f"{result.max_variance:>14}{len(result.failures):>11}"
        )
        for problem in result.problems[:5]:
            write(f"    {problem}")

    if RESULTS:
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        with REPORT.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f, lineterminator="\n")
            writer.writerow(
                ["case", "check", "key", "expected", "actual", "difference", "tolerance", "result"]
            )
            for result in RESULTS.values():
                for v in result.variances:
                    over = v.difference > result.tolerance
                    writer.writerow(
                        [
                            v.case,
                            v.check,
                            v.key,
                            v.expected,
                            v.actual,
                            v.difference,
                            result.tolerance,
                            "FAIL" if over else "pass",
                        ]
                    )
        write(f"Variance report: {REPORT}")


@pytest.fixture
def results() -> dict[str, CaseResult]:
    return RESULTS
