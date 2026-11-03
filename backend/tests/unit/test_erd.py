"""P1-T1: docs/erd.md is generated from the models and must stay in sync."""

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def test_erd_is_up_to_date() -> None:
    spec = importlib.util.spec_from_file_location("gen_erd", REPO / "tools" / "gen_erd.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    current = (REPO / "docs" / "erd.md").read_text(encoding="utf-8")
    assert current == module.render(), "docs/erd.md is stale: run `make erd`"
