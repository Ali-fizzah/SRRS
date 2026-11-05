"""Variance report -> test report, as Markdown and PDF (plan §11, task P6-T4). `make report`.

Reads what `make bench` wrote to benchmarks/reports/ and the cases themselves. It states what the
data shows: it stays marked DRAFT until every expected value and accounting decision is confirmed,
and the signature lines stay empty for the people who sign.
"""

import argparse
import csv
import re
from collections import Counter
from datetime import date
from decimal import Decimal
from pathlib import Path

import yaml
from fpdf import FPDF
from fpdf.enums import XPos, YPos

LEVELS = ["Unit", "Bundle", "Events", "Journals", "Close", "Excel", "Load", "Generated"]
LIMIT_LIST = 15


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _unsigned_decisions(plan: Path) -> list[str]:
    """Rows of plan §2 still waiting for M1."""
    rows = []
    for line in plan.read_text(encoding="utf-8").splitlines():
        match = re.match(r"\|\s*(D\d+)\s*\|\s*(.*?)\s*\|.*\*\*M1 sign-off\*\*\s*\|$", line)
        if match:
            summary = re.sub(r"\*\*|`", "", match.group(2))
            rows.append(f"{match.group(1)}: {summary.split('. ')[0].rstrip('.')}")
    return rows


def _source(meta: dict) -> str:
    if meta["status"] == "stub":
        return "-"
    return "Workbook" if meta["level"] == "Excel" else "Developer draft"


def _short(value: str) -> str:
    """Excel holds long unrounded amounts; four places show the difference."""
    number = Decimal(value)
    rounded = number.quantize(Decimal("0.0001"))
    return str(rounded.normalize()) if rounded == number else f"{rounded}..."


def collect(repo: Path, commit: str = "unknown") -> dict:
    """Everything the report says, worked out from the files."""
    reports = repo / "benchmarks" / "reports"
    results = {row["case"]: row for row in _read_csv(reports / "cases.csv")}
    variances = _read_csv(reports / "variance.csv")

    cases = []
    for folder in sorted((repo / "benchmarks" / "cases").iterdir()):
        if not folder.is_dir():
            continue
        meta = yaml.safe_load((folder / "case.yaml").read_text(encoding="utf-8"))
        notes = " ".join(str(note) for note in meta.get("notes") or [])
        cases.append(
            {
                "name": folder.name,
                "level": meta["level"],
                "status": meta["status"],
                "description": meta["description"],
                "draft": "DRAFT" in notes,
                "source": _source(meta),
                "result": results.get(folder.name),
            }
        )
    for name, row in results.items():
        if not (repo / "benchmarks" / "cases" / name).is_dir():
            cases.append(
                {
                    "name": name,
                    "level": "Generated",
                    "status": "ready",
                    "description": "Seeded dataset, tools/generate_dataset.py",
                    "draft": False,
                    "source": "Generator",
                    "result": row,
                }
            )
    cases.sort(key=lambda c: (LEVELS.index(c["level"]) if c["level"] in LEVELS else 99, c["name"]))

    differences = [
        (Decimal(v["difference"]), v) for v in variances if Decimal(v["difference"]) != 0
    ]
    differences.sort(key=lambda item: item[0], reverse=True)
    buckets = Counter()
    for v in variances:
        difference = Decimal(v["difference"])
        if difference == 0:
            buckets["0"] += 1
        elif difference <= Decimal("0.005"):
            buckets["up to 0.005"] += 1
        elif difference < Decimal("0.01"):
            buckets["above 0.005, below 0.01"] += 1
        elif difference == Decimal("0.01"):
            buckets["exactly 0.01"] += 1
        else:
            buckets["over 0.01"] += 1

    ran = [c for c in cases if c["result"]]
    failed = [c for c in ran if c["result"]["result"] != "PASS"]
    not_run = [c for c in cases if c["status"] == "ready" and not c["result"]]
    return {
        "date": date.today().isoformat(),
        "commit": commit,
        "cases": cases,
        "ran": ran,
        "failed": failed,
        "not_run": not_run,
        "stubs": [c for c in cases if c["status"] == "stub"],
        "drafts": [c for c in cases if c["draft"]],
        "compared": len(variances),
        "over": sum(1 for v in variances if v["result"] == "FAIL"),
        "max": max((item[0] for item in differences), default=Decimal(0)),
        "buckets": buckets,
        "largest": [item[1] for item in differences[:LIMIT_LIST]],
        "unsigned": _unsigned_decisions(repo / "docs" / "DEVELOPMENT_PLAN.md"),
    }


def status_lines(data: dict) -> tuple[str, list[str]]:
    """The headline, and every reason the report is not final."""
    reasons = []
    if data["failed"]:
        reasons.append(f"{len(data['failed'])} case(s) failed.")
    if data["not_run"]:
        reasons.append(f"{len(data['not_run'])} ready case(s) were not run.")
    if data["drafts"]:
        reasons.append(
            f"{len(data['drafts'])} case(s) use expected values M1 has not confirmed "
            "(drafted by the developers)."
        )
    if data["unsigned"]:
        reasons.append(f"{len(data['unsigned'])} accounting decision(s) are not signed off.")
    if data["stubs"]:
        reasons.append(f"{len(data['stubs'])} case(s) are not built yet.")
    if data["failed"] or data["not_run"]:
        return "FAILED: this run does not meet the pass rule.", reasons
    if reasons:
        return "DRAFT: the run passes, but the report cannot be signed yet.", reasons
    return "READY TO SIGN: every case passes and nothing is outstanding.", reasons


PASS_RULE = (
    "Every schedule and journal amount within 0.01 of the expected value, and every obligation's "
    "schedule total exactly equal to its allocation (plan §11.1)."
)
WHY_NOT_ZERO = (
    '"Zero variance" here means no amount is outside the 0.01 tolerance. It does not mean every '
    "difference is 0.00: Excel holds unrounded amounts and the system holds cents, so differences "
    "up to the tolerance are expected (plan §11.4)."
)


def to_markdown(data: dict) -> str:
    headline, reasons = status_lines(data)
    out = [
        "# Revenue recognition system: test report",
        "",
        f"Date: {data['date']} · Code version: `{data['commit']}`",
        "",
        f"**{headline}**",
        "",
    ]
    out += [f"- {reason}" for reason in reasons]
    out += [
        "",
        "## Result",
        "",
        f"- Cases run: **{len(data['ran'])}**, failed: **{len(data['failed'])}**",
        f"- Amounts compared: **{data['compared']}**, outside tolerance: **{data['over']}**",
        f"- Largest difference: **{data['max']}**",
        "",
        f"Pass rule: {PASS_RULE}",
        "",
        WHY_NOT_ZERO,
        "",
        "## Per case",
        "",
        "| Case | Level | Expected values from | Result | Compared | Max variance | Outside 0.01 |",
        "|---|---|---|---|---:|---:|---:|",
    ]
    for case in data["cases"]:
        row = case["result"]
        if row:
            out.append(
                f"| {case['name']} | {case['level']} | {case['source']} | {row['result']} | "
                f"{row['compared']} | {row['max_variance']} | {row['over_tolerance']} |"
            )
        else:
            label = "Not built" if case["status"] == "stub" else "NOT RUN"
            out.append(f"| {case['name']} | {case['level']} | {case['source']} | {label} | | | |")
    out += ["", "## How the differences spread", "", "| Difference | Amounts |", "|---|---:|"]
    for bucket in ("0", "up to 0.005", "above 0.005, below 0.01", "exactly 0.01", "over 0.01"):
        out.append(f"| {bucket} | {data['buckets'][bucket]} |")
    if data["buckets"]["exactly 0.01"]:
        out += [
            "",
            f"{data['buckets']['exactly 0.01']} amount(s) sit exactly at 0.01. They pass only "
            'because the rule says "within 0.01", read as including 0.01. M1 should confirm '
            "that reading.",
        ]
    if data["largest"]:
        out += [
            "",
            "## Largest differences",
            "",
            "| Case | Check | Item | Expected | Actual | Difference |",
            "|---|---|---|---:|---:|---:|",
        ]
        out += [
            f"| {v['case']} | {v['check']} | {v['key']} | {_short(v['expected'])} | "
            f"{_short(v['actual'])} | {_short(v['difference'])} |"
            for v in data["largest"]
        ]
    if data["unsigned"]:
        out += ["", "## Decisions waiting for sign-off", ""]
        out += [f"- {item}" for item in data["unsigned"]]
    out += [
        "",
        "## Sign-off",
        "",
        "| Role | Name | Signature | Date |",
        "|---|---|---|---|",
        "| Accounting lead (M1) | | | |",
        "| Project advisor | | | |",
        "",
    ]
    return "\n".join(out)


def _latin(text: object) -> str:
    """The PDF's built-in fonts hold Latin-1 only."""
    return str(text).replace("·", "-").encode("latin-1", "replace").decode("latin-1")


def _heading(pdf: FPDF, text: str) -> None:
    if pdf.get_y() > 235:  # keep a heading with the table under it
        pdf.add_page()
    pdf.ln(3)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, _latin(text), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", "", 9)


def _para(pdf: FPDF, text: str, bold: bool = False) -> None:
    pdf.set_font("Helvetica", "B" if bold else "", 9)
    pdf.multi_cell(0, 5, _latin(text), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", "", 9)


def _table(pdf: FPDF, header: list[str], rows: list[list[object]], widths: tuple[int, ...]) -> None:
    pdf.set_font("Helvetica", "", 8)
    with pdf.table(col_widths=widths, text_align="LEFT", line_height=5) as table:
        head = table.row()
        for cell in header:
            head.cell(_latin(cell))
        for row in rows:
            cells = table.row()
            for cell in row:
                cells.cell(_latin(cell))
    pdf.set_font("Helvetica", "", 9)


def to_pdf(data: dict, path: Path) -> None:
    headline, reasons = status_lines(data)
    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, "Revenue recognition system: test report", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    _para(pdf, f"Date: {data['date']} - Code version: {data['commit']}")
    pdf.ln(2)
    _para(pdf, headline, bold=True)
    for reason in reasons:
        _para(pdf, f"- {reason}")

    _heading(pdf, "Result")
    _para(pdf, f"Cases run: {len(data['ran'])}, failed: {len(data['failed'])}")
    _para(pdf, f"Amounts compared: {data['compared']}, outside tolerance: {data['over']}")
    _para(pdf, f"Largest difference: {data['max']}")
    pdf.ln(1)
    _para(pdf, f"Pass rule: {PASS_RULE}")
    pdf.ln(1)
    _para(pdf, WHY_NOT_ZERO)

    _heading(pdf, "Per case")
    rows: list[list[object]] = []
    for case in data["cases"]:
        row = case["result"]
        if row:
            rows.append(
                [
                    case["name"],
                    case["level"],
                    case["source"],
                    row["result"],
                    row["compared"],
                    row["max_variance"],
                    row["over_tolerance"],
                ]
            )
        else:
            label = "Not built" if case["status"] == "stub" else "NOT RUN"
            rows.append([case["name"], case["level"], case["source"], label, "", "", ""])
    _table(
        pdf,
        ["Case", "Level", "Expected from", "Result", "Compared", "Max var.", "Over 0.01"],
        rows,
        (58, 18, 28, 16, 18, 16, 16),
    )

    _heading(pdf, "How the differences spread")
    buckets = ("0", "up to 0.005", "above 0.005, below 0.01", "exactly 0.01", "over 0.01")
    _table(pdf, ["Difference", "Amounts"], [[b, data["buckets"][b]] for b in buckets], (70, 30))
    if data["buckets"]["exactly 0.01"]:
        pdf.ln(1)
        _para(
            pdf,
            f"{data['buckets']['exactly 0.01']} amount(s) sit exactly at 0.01. They pass only "
            'because the rule says "within 0.01", read as including 0.01. M1 should confirm that '
            "reading.",
        )

    if data["largest"]:
        _heading(pdf, "Largest differences")
        _table(
            pdf,
            ["Case", "Check", "Item", "Expected", "Actual", "Diff."],
            [
                [
                    v["case"],
                    v["check"],
                    v["key"],
                    _short(v["expected"]),
                    _short(v["actual"]),
                    _short(v["difference"]),
                ]
                for v in data["largest"]
            ],
            (44, 16, 74, 18, 18, 14),
        )

    if data["unsigned"]:
        _heading(pdf, "Decisions waiting for sign-off")
        for item in data["unsigned"]:
            _para(pdf, f"- {item}")

    _heading(pdf, "Sign-off")
    _table(
        pdf,
        ["Role", "Name", "Signature", "Date"],
        [["Accounting lead (M1)", "", "", ""], ["Project advisor", "", "", ""]],
        (50, 50, 60, 30),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(path))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--commit", default="unknown", help="the code version, from git")
    args = parser.parse_args()
    data = collect(args.repo, args.commit)
    out = args.repo / "docs" / "test-report"
    out.mkdir(parents=True, exist_ok=True)
    (out / "test-report.md").write_text(to_markdown(data), encoding="utf-8")
    to_pdf(data, out / "test-report.pdf")
    print(status_lines(data)[0])
    print(f"Wrote {out / 'test-report.md'} and test-report.pdf")


if __name__ == "__main__":
    main()
