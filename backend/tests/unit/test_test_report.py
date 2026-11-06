"""P6-T4: the report must say what the data says, and never claim to be signed."""

import csv
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest
import yaml


def _load() -> ModuleType:
    path = Path(__file__).resolve().parents[3] / "tools" / "test_report.py"
    spec = importlib.util.spec_from_file_location("test_report_tool", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


tool = _load()


def _write(path: Path, rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(rows)


VARIANCE_HEADER = [
    "case",
    "check",
    "key",
    "expected",
    "actual",
    "difference",
    "tolerance",
    "result",
]
CASE_HEADER = ["case", "result", "compared", "max_variance", "over_tolerance", "problems"]


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    for name, level, status, notes in (
        ("X01_workbook", "Excel", "ready", []),
        ("B01_bundle", "Bundle", "ready", ["DRAFT by the developers"]),
        ("L01_load", "Load", "stub", []),
    ):
        folder = tmp_path / "benchmarks" / "cases" / name
        folder.mkdir(parents=True)
        (folder / "case.yaml").write_text(
            yaml.safe_dump({"level": level, "status": status, "description": name, "notes": notes}),
            encoding="utf-8",
        )
    reports = tmp_path / "benchmarks" / "reports"
    _write(
        reports / "variance.csv",
        [
            VARIANCE_HEADER,
            ["X01_workbook", "schedule", "K/1/202501", "9.45", "9.44", "0.01", "0.01", "pass"],
            ["B01_bundle", "schedule", "K/1/202501", "1.00", "1.00", "0.00", "0.01", "pass"],
        ],
    )
    _write(
        reports / "cases.csv",
        [
            CASE_HEADER,
            ["X01_workbook", "PASS", "1", "0.01", "0", "0"],
            ["B01_bundle", "PASS", "1", "0.00", "0", "0"],
        ],
    )
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "DEVELOPMENT_PLAN.md").write_text(
        "| D1 | Money is cents. | Why | Locked |\n"
        "| D2 | Rounding is half up. More text. | Why | **M1 sign-off** |\n",
        encoding="utf-8",
    )
    return tmp_path


def test_a_passing_run_with_drafts_is_a_draft_not_ready_to_sign(repo: Path) -> None:
    text = tool.to_markdown(tool.collect(repo))
    assert "DRAFT: the run passes" in text
    assert "1 case(s) use expected values M1 has not confirmed" in text
    assert "1 accounting decision(s) are not signed off" in text
    assert "D2: Rounding is half up" in text
    assert "READY TO SIGN" not in text


def test_it_reports_amounts_at_the_limit_and_does_not_call_them_zero(repo: Path) -> None:
    text = tool.to_markdown(tool.collect(repo))
    assert "Largest difference: **0.01**" in text
    assert "1 amount(s) sit exactly at 0.01" in text
    assert "does not mean every difference is 0.00" in text.replace("\n", " ")


def test_a_failed_case_makes_the_report_failed(repo: Path) -> None:
    _write(
        repo / "benchmarks" / "reports" / "cases.csv",
        [
            CASE_HEADER,
            ["X01_workbook", "FAIL", "1", "5.00", "1", "0"],
            ["B01_bundle", "PASS", "1", "0.00", "0", "0"],
        ],
    )
    assert "FAILED" in tool.to_markdown(tool.collect(repo))


def test_a_ready_case_that_did_not_run_is_not_a_pass(repo: Path) -> None:
    _write(
        repo / "benchmarks" / "reports" / "cases.csv",
        [CASE_HEADER, ["X01_workbook", "PASS", "1", "0.01", "0", "0"]],
    )
    text = tool.to_markdown(tool.collect(repo))
    assert "FAILED" in text and "NOT RUN" in text


def test_it_can_become_ready_only_when_nothing_is_outstanding(repo: Path) -> None:
    for name in ("B01_bundle", "L01_load"):
        folder = repo / "benchmarks" / "cases" / name
        (folder / "case.yaml").write_text(
            yaml.safe_dump(
                {"level": "Bundle", "status": "ready", "description": name, "notes": []}
            ),
            encoding="utf-8",
        )
    _write(
        repo / "benchmarks" / "reports" / "cases.csv",
        [
            CASE_HEADER,
            ["X01_workbook", "PASS", "1", "0.01", "0", "0"],
            ["B01_bundle", "PASS", "1", "0.00", "0", "0"],
            ["L01_load", "PASS", "1", "0.00", "0", "0"],
        ],
    )
    (repo / "docs" / "DEVELOPMENT_PLAN.md").write_text(
        "| D2 | Rounding | Why | Locked |\n", "utf-8"
    )
    assert "READY TO SIGN" in tool.to_markdown(tool.collect(repo))


def test_signature_lines_are_empty_and_the_pdf_is_written(repo: Path, tmp_path: Path) -> None:
    data = tool.collect(repo)
    text = tool.to_markdown(data)
    assert "| Accounting lead (M1) | | | |" in text
    path = tmp_path / "out" / "report.pdf"
    tool.to_pdf(data, path)
    assert path.read_bytes().startswith(b"%PDF")
