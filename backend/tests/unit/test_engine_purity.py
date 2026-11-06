"""CLAUDE.md: app/engine is pure: no DB, no I/O, no clock, integer cents, never float."""

import ast
from pathlib import Path

import pytest

ENGINE = Path(__file__).resolve().parents[2] / "app" / "engine"
MODULES = sorted(ENGINE.glob("*.py"))

# The engine may import only itself and these standard-library helpers.
ALLOWED_IMPORTS = {
    "__future__",
    "calendar",
    "collections",
    "dataclasses",
    "datetime",
    "decimal",
    "enum",
    "math",
    "re",
    "typing",
    "numpy",  # §4: the engine works on NumPy arrays of cents
}
CLOCK_CALLS = {"now", "today", "utcnow"}
IO_NAMES = {"open", "print", "input"}


def _imported_roots(tree: ast.AST) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            module = node.module
            roots.add("app.engine" if module.startswith("app.engine") else module.split(".")[0])
    return roots


def test_the_engine_has_modules_to_check() -> None:
    assert {p.name for p in MODULES} >= {"methods.py", "money.py", "periods.py"}


@pytest.mark.parametrize("module", MODULES, ids=lambda p: p.name)
def test_engine_module_imports_nothing_impure(module: Path) -> None:
    tree = ast.parse(module.read_text(encoding="utf-8"))
    assert _imported_roots(tree) <= ALLOWED_IMPORTS | {"app.engine"}


@pytest.mark.parametrize("module", MODULES, ids=lambda p: p.name)
def test_engine_module_uses_no_float_clock_or_io(module: Path) -> None:
    tree = ast.parse(module.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            assert node.id != "float", f"{module.name}:{node.lineno} uses float (D1)"
            assert node.id not in IO_NAMES, f"{module.name}:{node.lineno} does I/O"
        if isinstance(node, ast.Attribute):
            assert node.attr not in CLOCK_CALLS, f"{module.name}:{node.lineno} reads the clock"
        if isinstance(node, ast.Constant):
            assert not isinstance(node.value, float), f"{module.name}:{node.lineno} float literal"
