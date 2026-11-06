"""Convert a REVREC Excel workbook into a benchmark case (plan §11.4, task P0-T5).

Usage:
    python benchmarks/tools/convert_revrec_xlsx.py <workbook.xlsx> <case_dir>

Writes, from the workbook's *calculated* values:
    inputs/<YYYYMM>/<template>.csv   system templates (plan §7), one folder per replay month
    expected/allocation.csv          CALCULATION.Allocated_revenue (separate obligations)
    expected/schedule.csv            CALCULATION period columns, non-zero cells
    expected/postings.csv            Transaction rows (Revenue_PPA, Revenue, New_Billing)
and updates source / open_period / periods in <case_dir>/case.yaml.

Excel values arrive as floats; they are converted to Decimal straight away via repr()
so nothing downstream does float arithmetic on money.
"""

from __future__ import annotations

import argparse
import csv
import shutil
import sys
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

import openpyxl
import yaml
from openpyxl.worksheet.worksheet import Worksheet

# Template headers, exact and in order (plan §7).
TEMPLATES: dict[str, list[str]] = {
    "customers": ["customer_id", "name", "country"],
    "products": [
        "product_id",
        "name",
        "category",
        "list_price",
        "ssp_source",
        "ssp_value",
        "ssp_pct",
        "recognition_method",
        "separate_obligation",
        "revenue_gl_account",
        "ssp_valid_from",
    ],
    "contracts": [
        "contract_id",
        "customer_id",
        "start_date",
        "end_date",
        "event_type",
        "effective_date",
    ],
    "contract_lines": [
        "contract_id",
        "line_no",
        "product_id",
        "quantity",
        "unit_price",
        "discount",
        "service_start",
        "service_end",
        "completion_date",
    ],
    "invoices": ["invoice_number", "contract_id", "invoice_date", "line_no", "amount"],
    "deliveries": ["delivery_id", "contract_id", "line_no", "delivery_date", "units_fraction"],
}

# Excel recognition method -> system method (plan §11.4, D3).
METHOD_MAP = {
    "RATABLE": "RATABLE_DAILY",
    "POINT_IN_TIME": "POINT_IN_TIME",
    "PROPORTIONAL_PERFORMANCE": "POINT_IN_TIME",
}
OBLIGATION_SUFFIXES = ("_Print", "_Digital")

# Synthesised fields the workbook does not carry. Not accounting rules: test-data choices.
CUSTOMER_COUNTRY = "US"
REVENUE_ACCOUNT_PRINT = "4200"  # Print / Hardware Revenue (plan §5.7 default chart)
REVENUE_ACCOUNT_OTHER = "4100"  # Subscription Revenue

CENT = Decimal("0.01")


class ConversionError(Exception):
    pass


# --------------------------------------------------------------------------- helpers


def dec(value: Any) -> Decimal:
    """Excel cell -> Decimal without float arithmetic (blank -> 0)."""
    if value is None or value == "":
        return Decimal(0)
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(str(value))


def money(value: Any, where: str) -> str:
    """Format an input amount; it must already be whole cents."""
    d = dec(value)
    if d != d.quantize(CENT):
        raise ConversionError(f"{where}: amount {d} has more than 2 decimals")
    return str(d.quantize(CENT))


def plain(d: Decimal, places: int = 10) -> str:
    """Decimal -> fixed-point string without trailing zeros (keeps Excel precision)."""
    text = format(d.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def as_date(value: Any, where: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raise ConversionError(f"{where}: expected a date, got {value!r}")


def period_of(d: date) -> str:
    return f"{d.year:04d}{d.month:02d}"


def text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def header_index(row: Sequence[Any], names: Iterable[str], where: str) -> dict[str, int]:
    """Map header name -> 0-based column index; fail if any is missing."""
    found = {text(v): i for i, v in enumerate(row) if v is not None}
    missing = [n for n in names if n not in found]
    if missing:
        raise ConversionError(f"{where}: missing columns {missing}")
    return {n: found[n] for n in names}


def find_header_row(ws: Worksheet, first_header: str, max_scan: int = 20) -> int:
    for r in range(1, max_scan + 1):
        if text(ws.cell(r, 1).value) == first_header:
            return r
    raise ConversionError(f"{ws.title}: header row starting with {first_header!r} not found")


def months_between(first: str, last: str) -> list[str]:
    y, m = int(first[:4]), int(first[4:])
    out = []
    while f"{y:04d}{m:02d}" <= last:
        out.append(f"{y:04d}{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


# --------------------------------------------------------------------------- reading


@dataclass
class Line:
    row: int  # worksheet row, shared by Input_SaleOrderDetails and CALCULATION
    contract_id: str
    line_no: str
    posting_date: date
    product_id: str
    bookings: Decimal
    quantity: Decimal
    sale_price: Any
    service_start: date
    service_end: date
    invoice_number: str
    subscription_id: str


@dataclass
class Rule:
    product_id: str
    policy: str
    amount: Any
    method: str

    @property
    def separate(self) -> bool:
        """D4: SSP 0 bundle header lines (no _Print/_Digital suffix) are not obligations."""
        return not (dec(self.amount) == 0 and not self.product_id.endswith(OBLIGATION_SUFFIXES))


def read_lines(wb: openpyxl.Workbook) -> list[Line]:
    ws = wb["Input_SaleOrderDetails"]
    hr = find_header_row(ws, "Instrumentid")
    cols = header_index(
        [c.value for c in ws[hr]],
        [
            "Instrumentid",
            "subInstrumentid",
            "PostingDate",
            "Product_ID",
            "Bookings_amount",
            "Quantity",
            "Sale_price",
            "Service_start_date",
            "Service_end_date",
            "Invoice_number",
            "Subscription_Id",
        ],
        ws.title,
    )
    lines = []
    for r, row in enumerate(ws.iter_rows(min_row=hr + 1, values_only=True), start=hr + 1):
        if not text(row[cols["Instrumentid"]]):
            continue
        where = f"{ws.title}!row {r}"
        lines.append(
            Line(
                row=r,
                contract_id=text(row[cols["Instrumentid"]]),
                line_no=text(row[cols["subInstrumentid"]]),
                posting_date=as_date(row[cols["PostingDate"]], where),
                product_id=text(row[cols["Product_ID"]]),
                bookings=dec(row[cols["Bookings_amount"]]),
                quantity=dec(row[cols["Quantity"]]),
                sale_price=row[cols["Sale_price"]],
                service_start=as_date(row[cols["Service_start_date"]], where),
                service_end=as_date(row[cols["Service_end_date"]], where),
                invoice_number=text(row[cols["Invoice_number"]]),
                subscription_id=text(row[cols["Subscription_Id"]]),
            )
        )
    return lines


def read_rules(wb: openpyxl.Workbook) -> dict[str, Rule]:
    ws = wb["Input_SSPRule"]
    hr = find_header_row(ws, "Product_Code")
    cols = header_index(
        [c.value for c in ws[hr]],
        ["Product_Code", "Standalone Price Policy", "Amount", "Recognition Method"],
        ws.title,
    )
    rules = {}
    for row in ws.iter_rows(min_row=hr + 1, values_only=True):
        code = text(row[cols["Product_Code"]])
        if not code:
            continue
        method = text(row[cols["Recognition Method"]])
        if method not in METHOD_MAP:
            raise ConversionError(f"{ws.title}: unknown recognition method {method!r} for {code}")
        policy = text(row[cols["Standalone Price Policy"]])
        if policy != "DOLLAR_AMOUNT":
            raise ConversionError(f"{ws.title}: unsupported SSP policy {policy!r} for {code}")
        rules[code] = Rule(code, policy, row[cols["Amount"]], method)
    return rules


# --------------------------------------------------------------------------- conversion


def build_inputs(
    lines: list[Line], rules: dict[str, Rule], wb: openpyxl.Workbook
) -> tuple[dict[str, dict[str, list[list[str]]]], str, str]:
    """Return {period: {template: rows}}, first replay period, last delivery posting period."""
    out: dict[str, dict[str, list[list[str]]]] = defaultdict(lambda: defaultdict(list))

    by_contract: dict[str, list[Line]] = defaultdict(list)
    for ln in lines:
        if ln.product_id not in rules:
            raise ConversionError(f"row {ln.row}: product {ln.product_id} has no SSP rule")
        by_contract[ln.contract_id].append(ln)

    contract_period: dict[str, str] = {}
    for cid, cl in by_contract.items():
        periods = {period_of(ln.posting_date) for ln in cl}
        if len(periods) != 1:
            raise ConversionError(f"contract {cid}: lines have different PostingDates {periods}")
        contract_period[cid] = periods.pop()

    first_period = min(contract_period.values())
    ssp_valid_from = min(ln.service_start for ln in lines).isoformat()

    for code, rule in rules.items():
        amount = money(rule.amount, f"Input_SSPRule {code}")
        out[first_period]["products"].append(
            [
                code,
                code,
                "",
                amount,
                "FIXED",
                amount,
                "",
                METHOD_MAP[rule.method],
                "Y" if rule.separate else "N",
                REVENUE_ACCOUNT_PRINT if code.endswith("_Print") else REVENUE_ACCOUNT_OTHER,
                ssp_valid_from,
            ]
        )

    for cid, cl in by_contract.items():
        p = contract_period[cid]
        subs = {ln.subscription_id for ln in cl}
        if len(subs) != 1:
            raise ConversionError(f"contract {cid}: several Subscription_Id values {subs}")
        sub = subs.pop()
        customer_id = f"CUST-{sub}"
        out[p]["customers"].append([customer_id, f"Customer {sub}", CUSTOMER_COUNTRY])
        start = min(ln.service_start for ln in cl).isoformat()
        end = max(ln.service_end for ln in cl).isoformat()
        out[p]["contracts"].append([cid, customer_id, start, end, "NEW", start])

        for ln in sorted(cl, key=lambda x: int(x.line_no)):
            rule = rules[ln.product_id]
            completion = ""
            if rule.separate and rule.method == "POINT_IN_TIME":
                completion = ln.service_start.isoformat()  # Excel recognises in the start month
            elif rule.separate and rule.method == "PROPORTIONAL_PERFORMANCE":
                completion = ln.service_end.isoformat()  # undelivered remainder at service end (D3)
            out[p]["contract_lines"].append(
                [
                    cid,
                    ln.line_no,
                    ln.product_id,
                    plain(ln.quantity, 4),
                    money(ln.sale_price, f"row {ln.row} Sale_price"),
                    "0.00",
                    ln.service_start.isoformat(),
                    ln.service_end.isoformat(),
                    completion,
                ]
            )
            if ln.bookings != 0:
                out[p]["invoices"].append(
                    [
                        ln.invoice_number,
                        cid,
                        ln.posting_date.isoformat(),
                        ln.line_no,
                        money(ln.bookings, f"row {ln.row} Bookings_amount"),
                    ]
                )

    last_delivery_period = first_period
    ws = wb["inp_ProfessionalServiceDelivery"]
    hr = find_header_row(ws, "PostingDate")
    cols = header_index(
        [c.value for c in ws[hr]],
        [
            "PostingDate",
            "EffectiveDate",
            "InstrumentId",
            "AttributeId",
            "Units_Delivered",
            "Service_Delivery_Id",
        ],
        ws.title,
    )
    for r, row in enumerate(ws.iter_rows(min_row=hr + 1, values_only=True), start=hr + 1):
        cid = text(row[cols["InstrumentId"]])
        if not cid:
            continue
        where = f"{ws.title}!row {r}"
        p = period_of(as_date(row[cols["PostingDate"]], where))
        if cid not in contract_period:
            raise ConversionError(f"{where}: unknown contract {cid}")
        if p < contract_period[cid]:
            raise ConversionError(f"{where}: delivery posted before its contract ({p})")
        last_delivery_period = max(last_delivery_period, p)
        out[p]["deliveries"].append(
            [
                text(row[cols["Service_Delivery_Id"]]),
                cid,
                text(row[cols["AttributeId"]]),
                as_date(row[cols["EffectiveDate"]], where).isoformat(),
                plain(dec(row[cols["Units_Delivered"]]), 6),
            ]
        )

    return out, first_period, last_delivery_period


def build_allocation_and_schedule(
    lines: list[Line], rules: dict[str, Rule], wb: openpyxl.Workbook
) -> tuple[list[list[str]], list[list[str]]]:
    ws = wb["CALCULATION"]
    hr = find_header_row(ws, "Standalone Price Policy")
    header = [c.value for c in ws[hr]]
    alloc_col = header_index(header, ["Allocated_revenue"], ws.title)["Allocated_revenue"] + 1

    # Period columns: those right of the "Period No ==>" label; keys from the Actg_Period row.
    label_col = header_index(header, ["Period No ==>"], ws.title)["Period No ==>"] + 1
    period_row = next(
        (r for r in range(1, hr) if text(ws.cell(r, label_col).value) == "Actg_Period"), None
    )
    if period_row is None:
        raise ConversionError(f"{ws.title}: 'Actg_Period' row not found")
    period_cols: list[tuple[int, str]] = []
    for c in range(label_col + 1, ws.max_column + 1):
        key = text(ws.cell(period_row, c).value)
        if key:
            period_cols.append((c, key))

    allocation, schedule = [], []
    for ln in lines:
        alloc_value = ws.cell(ln.row, alloc_col).value
        if alloc_value is None:
            raise ConversionError(
                f"{ws.title}!row {ln.row}: no calculated value; open the workbook in Excel, "
                "recalculate and save, then convert again"
            )
        if not rules[ln.product_id].separate:
            continue
        allocation.append([ln.contract_id, ln.line_no, str(dec(alloc_value).quantize(CENT))])
        for c, key in period_cols:
            amount = dec(ws.cell(ln.row, c).value)
            if amount != 0:
                schedule.append([ln.contract_id, ln.line_no, key, plain(amount)])
    return allocation, schedule


def build_postings(wb: openpyxl.Workbook) -> tuple[list[list[str]], str]:
    """Transaction sheet -> postings.csv rows and the last posting period."""
    ws = wb["Transaction"]
    hr = find_header_row(ws, "PostingDate")
    cols = header_index(
        [c.value for c in ws[hr]],
        ["PostingDate", "Instrumentid", "attributeId", "TransactionName", "Amount"],
        ws.title,
    )
    entry_types = {
        "Revenue_PPA": "REVENUE_CATCH_UP",
        "Revenue": "REVENUE",
        "New_Billing": "INVOICE",
    }
    totals: dict[tuple[str, str, str, str], Decimal] = defaultdict(Decimal)
    last = ""
    for r, row in enumerate(ws.iter_rows(min_row=hr + 1, values_only=True), start=hr + 1):
        posting = row[cols["PostingDate"]]
        if not isinstance(posting, datetime | date):
            continue  # trailing notes below the table
        name = text(row[cols["TransactionName"]])
        if name not in entry_types:
            raise ConversionError(f"{ws.title}!row {r}: unknown TransactionName {name!r}")
        p = period_of(as_date(posting, f"{ws.title}!row {r}"))
        last = max(last, p)
        amount = dec(row[cols["Amount"]])
        # Excel stores revenue as a negative; postings.csv uses a positive credit.
        if entry_types[name] != "INVOICE":
            amount = -amount
        key = (
            p,
            text(row[cols["Instrumentid"]]),
            text(row[cols["attributeId"]]),
            entry_types[name],
        )
        totals[key] += amount
    rows = [[p, cid, line, et, plain(amt)] for (p, cid, line, et), amt in totals.items()]
    rows.sort(key=lambda x: (x[0], x[1], int(x[2]), x[3]))
    return rows, last


# --------------------------------------------------------------------------- writing


def write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)


def update_case_yaml(case_dir: Path, source: str, first: str, last: str) -> None:
    path = case_dir / "case.yaml"
    data: dict[str, Any] = {}
    if path.exists():
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    data.update(
        {
            "source": source,
            "open_period": first,
            "periods": {"from": first, "to": last},
            "status": "ready",
        }
    )
    data.setdefault("tolerance", "0.01")
    data.setdefault("notes", [])
    header = (
        "# Benchmark case (plan §11.2-11.3). Expected values are owned by M1.\n"
        "# inputs/ and expected/ are generated by benchmarks/tools/convert_revrec_xlsx.py.\n"
        "# Never edit expected/ to make a test pass;\n"
        "# record confirmed benchmark fixes under notes.\n"
    )
    path.write_text(header + yaml.safe_dump(data, sort_keys=False, allow_unicode=True), "utf-8")


def convert(workbook: Path, case_dir: Path) -> dict[str, int]:
    """Convert one workbook; returns row counts per output for reporting and tests."""
    wb = openpyxl.load_workbook(workbook, data_only=True)
    lines = read_lines(wb)
    rules = read_rules(wb)
    inputs, first, last_delivery = build_inputs(lines, rules, wb)
    allocation, schedule = build_allocation_and_schedule(lines, rules, wb)
    postings, last_posting = build_postings(wb)
    last_service = period_of(max(ln.service_end for ln in lines))
    last = max(last_service, last_posting, last_delivery)

    for sub in ("inputs", "expected"):
        if (case_dir / sub).exists():
            shutil.rmtree(case_dir / sub)
    for period, templates in inputs.items():
        for name, rows in templates.items():
            write_csv(case_dir / "inputs" / period / f"{name}.csv", TEMPLATES[name], rows)
    exp = case_dir / "expected"
    write_csv(exp / "allocation.csv", ["contract_id", "line_no", "allocated_amount"], allocation)
    write_csv(
        exp / "schedule.csv", ["contract_id", "line_no", "service_period", "amount"], schedule
    )
    write_csv(
        exp / "postings.csv",
        ["posting_period", "contract_id", "line_no", "entry_type", "amount"],
        postings,
    )
    update_case_yaml(case_dir, f"benchmarks/source/{workbook.name}", first, last)

    counts = {name: 0 for name in TEMPLATES}
    for templates in inputs.values():
        for name, rows in templates.items():
            counts[name] += len(rows)
    counts.update(
        {
            "replay_months": len(months_between(first, last)),
            "allocation": len(allocation),
            "schedule": len(schedule),
            "postings": len(postings),
        }
    )
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("workbook", type=Path)
    parser.add_argument("case_dir", type=Path)
    args = parser.parse_args(argv)
    try:
        counts = convert(args.workbook, args.case_dir)
    except ConversionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    for name, n in counts.items():
        print(f"{name:15} {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
