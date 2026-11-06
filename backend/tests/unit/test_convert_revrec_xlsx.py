"""P0-T5: Excel workbook -> benchmark case conversion (plan §11.4)."""

import csv
import importlib.util
import sys
from decimal import Decimal
from pathlib import Path
from types import ModuleType

import pytest

REPO = Path(__file__).resolve().parents[3]
SOURCE = REPO / "benchmarks" / "source"


def _load_converter() -> ModuleType:
    path = REPO / "benchmarks" / "tools" / "convert_revrec_xlsx.py"
    spec = importlib.util.spec_from_file_location("convert_revrec_xlsx", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look up their module here
    spec.loader.exec_module(module)
    return module


converter = _load_converter()


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


@pytest.fixture(scope="module")
def x01(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict[str, int]]:
    case = tmp_path_factory.mktemp("X01")
    return case, converter.convert(SOURCE / "REVREC_Model_Final.xlsx", case)


@pytest.fixture(scope="module")
def x02(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict[str, int]]:
    case = tmp_path_factory.mktemp("X02")
    return case, converter.convert(SOURCE / "REVREC_Mock_Data.xlsx", case)


def test_x02_row_counts(x02: tuple[Path, dict[str, int]]) -> None:
    _, counts = x02
    assert counts["contract_lines"] == 60
    assert counts["deliveries"] == 22
    assert counts["invoices"] == 20
    assert counts["contracts"] == 20


def test_x02_replays_jan_2025_to_dec_2027(x02: tuple[Path, dict[str, int]]) -> None:
    case, counts = x02
    text = (case / "case.yaml").read_text(encoding="utf-8")
    assert "from: '202501'" in text
    assert "to: '202712'" in text
    assert counts["replay_months"] == 36


def test_x01_keeps_leading_zeros_and_bundle_headers(x01: tuple[Path, dict[str, int]]) -> None:
    case, _ = x01
    lines = _rows(case / "inputs" / "202505" / "contract_lines.csv")
    assert {r["contract_id"] for r in lines} == {"005984699-INV_106000494"}
    products = {r["product_id"]: r for r in _rows(case / "inputs" / "202505" / "products.csv")}
    assert products["COS_PRTDIG_MGRT_US_New_15_1200_0300"]["separate_obligation"] == "N"  # D4
    assert products["COS_PRTDIG_MGRT_US_New_15_1200_0300_Digital"]["recognition_method"] == (
        "RATABLE_DAILY"
    )


def test_x01_expected_values(x01: tuple[Path, dict[str, int]]) -> None:
    case, _ = x01
    allocation = _rows(case / "expected" / "allocation.csv")
    assert len(allocation) == 6  # bundle header lines are not obligations
    postings = {
        (r["posting_period"], r["contract_id"], r["line_no"], r["entry_type"]): r["amount"]
        for r in _rows(case / "expected" / "postings.csv")
    }
    # Plan §5.4 example: Jan-Jun booked as one catch-up in 202507.
    assert postings[("202507", "005984698-INV_106000493", "3", "REVENUE_CATCH_UP")] == "5.5044"
    assert postings[("202507", "005984698-INV_106000493", "1", "INVOICE")] == "30"


def test_schedule_totals_equal_allocation(x02: tuple[Path, dict[str, int]]) -> None:
    case, _ = x02
    totals: dict[tuple[str, str], Decimal] = {}
    for r in _rows(case / "expected" / "schedule.csv"):
        key = (r["contract_id"], r["line_no"])
        totals[key] = totals.get(key, Decimal(0)) + Decimal(r["amount"])
    for r in _rows(case / "expected" / "allocation.csv"):
        total = totals.get((r["contract_id"], r["line_no"]), Decimal(0))
        assert abs(total - Decimal(r["allocated_amount"])) < Decimal("0.000001")
