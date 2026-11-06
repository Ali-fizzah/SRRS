"""Benchmark case folders are well-formed (plan §11.2). The replay runner arrives in P3-T7."""

from pathlib import Path

import pytest
import yaml

CASES = Path(__file__).resolve().parents[3] / "benchmarks" / "cases"
EXPECTED_IDS = {
    "U01", "U02", "U03", "B01", "B02", "B03", "E01", "E02", "E03",
    "J01", "J02", "J03", "C01", "X01", "X02", "L01",
}  # fmt: skip
EXPECTED_FILES = ("allocation.csv", "schedule.csv", "postings.csv")


def _cases() -> list[Path]:
    return sorted(p for p in CASES.iterdir() if p.is_dir())


def test_every_planned_case_has_a_folder() -> None:
    ids = {yaml.safe_load((p / "case.yaml").read_text(encoding="utf-8"))["id"] for p in _cases()}
    assert ids == EXPECTED_IDS


@pytest.mark.parametrize("case", _cases(), ids=lambda p: p.name)
def test_case_yaml_is_valid(case: Path) -> None:
    meta = yaml.safe_load((case / "case.yaml").read_text(encoding="utf-8"))
    assert case.name.startswith(meta["id"])
    assert meta["tolerance"] == "0.01"
    assert meta["status"] in {"stub", "ready", "manual"}  # manual: run by `make load`, not here
    if meta["status"] == "ready":
        assert meta["open_period"] == meta["periods"]["from"]
        assert meta["periods"]["from"] <= meta["periods"]["to"]
        assert any((case / "inputs").iterdir())
        for name in EXPECTED_FILES:
            assert (case / "expected" / name).is_file(), name
