"""Generate a realistic dataset of any size as a golden case (plan §11.4, task P6-T1).

    python ../tools/generate_dataset.py --lines 5000 --seed 7 --profile full

Writes inputs/<YYYYMM>/*.csv in the system templates, so it goes through real ingestion, and
expected/ next to them, so `tests.benchmarks.runner.replay` can check every amount.

The expected values are worked out HERE, with exact fractions and the plan's rules written out
again, and never by importing app.engine. A bug in the engine therefore shows up as a variance.

Profiles run the plan's order (P6-T3): single contracts -> bundles -> events -> full.
"""

import argparse
import calendar
import csv
import random
import shutil
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from fractions import Fraction
from pathlib import Path

import yaml

HEADERS = {
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
    "credit_notes": ["credit_note_number", "invoice_number", "credit_date", "amount", "reason"],
    "deliveries": ["delivery_id", "contract_id", "line_no", "delivery_date", "units_fraction"],
}
MONTHLY, DAILY, POINT = "RATABLE_MONTHLY", "RATABLE_DAILY", "POINT_IN_TIME"


@dataclass(frozen=True)
class Product:
    code: str
    category: str
    list_cents: int
    source: str  # FIXED, LIST_PRICE, PCT_OF_LIST
    ssp_cents: int | None
    pct: int | None
    method: str
    separate: bool
    account: str


CATALOGUE = [
    Product("SUB-M", "Digital", 120000, "LIST_PRICE", None, None, MONTHLY, True, "4100"),
    Product("SUB-MF", "Digital", 110000, "FIXED", 100000, None, MONTHLY, True, "4100"),
    Product("SUB-MP", "Digital", 240000, "PCT_OF_LIST", None, 90, MONTHLY, True, "4100"),
    Product("SUB-D", "Digital", 365000, "LIST_PRICE", None, None, DAILY, True, "4100"),
    Product("SUB-DF", "Digital", 300000, "FIXED", 280000, None, DAILY, True, "4100"),
    Product("PRINT", "Print", 50000, "LIST_PRICE", None, None, POINT, True, "4200"),
    Product("SERVICE", "Services", 500000, "FIXED", 450000, None, POINT, True, "4300"),
    Product("HARDWARE", "Print", 80000, "PCT_OF_LIST", None, 75, POINT, True, "4200"),
    Product("SETUP", "Services", 50000, "LIST_PRICE", None, None, POINT, False, "4300"),
]
RATABLE = [p for p in CATALOGUE if p.method != POINT]
ITEMS = [p for p in CATALOGUE if p.method == POINT and p.separate]
SETUP = next(p for p in CATALOGUE if not p.separate)


def half_up(value: Fraction) -> int:
    return (2 * value.numerator + value.denominator) // (2 * value.denominator)


def money(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    return f"{sign}{abs(cents) // 100}.{abs(cents) % 100:02d}"


def key_of(when: date) -> str:
    return f"{when.year}{when.month:02d}"


def month_start(key: str) -> date:
    return date(int(key[:4]), int(key[4:]), 1)


def month_end(key: str) -> date:
    year, month = int(key[:4]), int(key[4:])
    return date(year, month, calendar.monthrange(year, month)[1])


def add_months(key: str, count: int) -> str:
    total = int(key[:4]) * 12 + int(key[4:]) - 1 + count
    return f"{total // 12}{total % 12 + 1:02d}"


def months(first: str, last: str) -> list[str]:
    out, key = [], first
    while key <= last:
        out.append(key)
        key = add_months(key, 1)
    return out


# --------------------------------------------------------------------------- the plan's rules


def allocate(entries: list[tuple[int, int, int, bool]]) -> dict[int, int]:
    """§5.2. entries: (line_no, net or remaining, SSP, separate). Plug: largest SSP, lowest line."""
    separate = sorted((e for e in entries if e[3]), key=lambda e: e[0])
    total_ssp = sum(e[2] for e in separate)
    tp = sum(e[1] for e in entries)
    out = {e[0]: half_up(Fraction(tp * e[2], total_ssp)) for e in separate}
    largest = min(separate, key=lambda e: (-e[2], e[0]))
    out[largest[0]] += tp - sum(out.values())
    return out


def schedule_monthly(a: int, start: date, end: date) -> dict[str, int]:
    keys = months(key_of(start), key_of(end))
    each = half_up(Fraction(a, len(keys)))
    return {k: each for k in keys[:-1]} | {keys[-1]: a - each * (len(keys) - 1)}


def schedule_daily(a: int, start: date, end: date, through: date | None = None) -> dict[str, int]:
    """§5.3 cumulative rounding; `through` stops at that date, cumulative to that day (§5.5)."""
    stop = min(through or end, end)
    if stop < start:
        return {}
    total = (end - start).days + 1
    out, previous = {}, 0
    for key in months(key_of(start), key_of(stop)):
        last = min(month_end(key), stop)
        cumulative = half_up(Fraction(a * ((last - start).days + 1), total))
        out[key], previous = cumulative - previous, cumulative
    return out


def schedule_point(
    a: int, completion: date, tranches: list[tuple[date, int]], through: date | None = None
) -> dict[str, int]:
    """§5.3 and D3: each delivery in its month; the remainder on completion, if reached."""
    stop = through or completion
    out: dict[str, int] = defaultdict(int)
    delivered = 0
    for when, fraction in tranches:
        amount = half_up(Fraction(a * fraction, 1_000_000))
        delivered += amount
        if when <= stop:
            out[key_of(when)] += amount
    if completion <= stop:
        out[key_of(completion)] += a - delivered
    return {k: v for k, v in out.items() if v}


@dataclass
class Obligation:
    line_no: int
    method: str
    ssp: int
    allocated: int
    start: date
    end: date
    completion: date | None
    tranches: list[tuple[date, int]]
    version: int
    earliest_posting: str
    earned: dict[str, int] = field(default_factory=dict)
    live: bool = True

    def schedule(self) -> dict[str, int]:
        if self.method == MONTHLY:
            return schedule_monthly(self.allocated, self.start, self.end)
        if self.method == DAILY:
            return schedule_daily(self.allocated, self.start, self.end)
        return schedule_point(self.allocated, self.completion or self.end, self.tranches)

    def earned_through(self, when: date) -> dict[str, int]:
        if self.method == DAILY:
            return schedule_daily(self.allocated, self.start, self.end, when)
        if self.method == POINT:
            return schedule_point(self.allocated, self.completion or self.end, self.tranches, when)
        if when < self.start:
            return {}
        return {k: v for k, v in self.schedule().items() if k <= key_of(when)}


@dataclass
class Line:
    no: int
    product: Product
    quantity: Fraction
    unit_cents: int
    discount_cents: int
    start: date
    end: date
    completion: date | None = None
    deliveries: list[tuple[date, int, str]] = field(default_factory=list)  # date, e6, upload month

    @property
    def net(self) -> int:
        return half_up(self.quantity * self.unit_cents) - self.discount_cents

    @property
    def ssp(self) -> int:
        product = self.product
        if product.source == "FIXED":
            return half_up(self.quantity * (product.ssp_cents or 0))
        if product.source == "LIST_PRICE":
            return half_up(self.quantity * product.list_cents)
        return half_up(self.quantity * product.list_cents * Fraction(product.pct or 0, 100))


def _quantity_text(value: Fraction) -> str:
    return str(float(value))


class Builder:
    def __init__(self, seed: int, profile: str, first: str, booking_months: int) -> None:
        self.rng = random.Random(seed)
        self.profile = profile
        self.first = first
        self.booking_months = booking_months
        self.files: dict[str, dict[str, list[list[str]]]] = defaultdict(lambda: defaultdict(list))
        self.allocation: list[list[str]] = []
        self.schedule: dict[tuple[str, int, str], int] = defaultdict(int)
        self.postings: dict[tuple[str, str, int, str], int] = defaultdict(int)  # this contract
        self.all_postings: dict[tuple[str, str, int, str], int] = {}
        self.document_months: dict[str, set[str]] = defaultdict(set)
        self.balances: list[list[str]] = []
        self.counter = {"invoice": 0, "credit": 0, "delivery": 0}
        self.stats: dict[str, int] = defaultdict(int)
        self.last_period = first

    # ----------------------------------------------------------------- one contract

    def _window(self, method: str, start_key: str, term: int) -> tuple[date, date]:
        if method == MONTHLY:
            return month_start(start_key), month_end(add_months(start_key, term - 1))
        start_day = self.rng.randint(1, 28)
        start = month_start(start_key).replace(day=start_day)
        end_key = add_months(start_key, term)
        return start, month_start(end_key).replace(day=start_day) - timedelta(days=1)

    def _line(self, no: int, product: Product, start_key: str, term: int) -> Line:
        quantity = Fraction(self.rng.choice(["1", "1", "1", "2", "3", "1.5", "0.5"]))
        unit = int(product.list_cents * self.rng.uniform(0.7, 1.1))
        gross = half_up(quantity * unit)
        discount = 0
        if self.rng.random() < 0.25:
            discount = int(gross * self.rng.choice([0.05, 0.1, 0.2, 0.333]))
        if product.method == POINT:
            start = month_start(start_key).replace(day=self.rng.randint(1, 28))
            end = start + timedelta(days=self.rng.randint(0, max(term, 1) * 28))
            return Line(no, product, quantity, unit, discount, start, end, end)
        start, end = self._window(product.method, start_key, term)
        return Line(no, product, quantity, unit, discount, start, end)

    def _lines(self, start_key: str, term: int, code: str) -> list[Line]:
        if self.profile == "single":
            return [self._line(1, self.rng.choice(CATALOGUE[:8]), start_key, term)]
        count = self.rng.randint(1, 4)
        lines = [self._line(1, self.rng.choice(RATABLE), start_key, term)]
        for no in range(2, count + 1):
            pool = ITEMS if self.rng.random() < 0.5 else RATABLE
            lines.append(self._line(no, self.rng.choice(pool), start_key, term))
        if self.rng.random() < 0.3:
            lines.append(self._line(len(lines) + 1, SETUP, start_key, 1))
        return lines

    def _add_deliveries(self, code: str, lines: list[Line], booked: str) -> None:
        """D3: tranches arrive by the delivery month, while completion is still unbooked."""
        for line in lines:
            if line.product.method != POINT or not line.product.separate:
                continue
            if self.rng.random() > 0.5 or line.completion is None:
                continue
            remaining = 1_000_000
            for _ in range(self.rng.randint(1, 3)):
                span = (line.completion - line.start).days
                when = line.start + timedelta(days=self.rng.randint(0, max(span, 0)))
                fraction = self.rng.choice([100000, 250000, 333333, 500000])
                if fraction > remaining:
                    break
                remaining -= fraction
                line.deliveries.append((when, fraction, max(key_of(when), booked)))
            line.deliveries.sort()

    def _write_version(
        self,
        code: str,
        customer: str,
        upload: str,
        event: str,
        effective: date,
        term: tuple[date, date],
        lines: list[Line],
    ) -> None:
        files = self.files[upload]
        files["contracts"].append(
            [code, customer, term[0].isoformat(), term[1].isoformat(), event, effective.isoformat()]
        )
        for line in lines:
            files["contract_lines"].append(
                [
                    code,
                    str(line.no),
                    line.product.code,
                    _quantity_text(line.quantity),
                    money(line.unit_cents),
                    money(line.discount_cents),
                    line.start.isoformat(),
                    line.end.isoformat(),
                    line.completion.isoformat() if line.completion else "",
                ]
            )

    def _invoice(self, code: str, upload: str, when: date, rows: list[tuple[int, int]]) -> str:
        self.counter["invoice"] += 1
        number = f"INV-{self.counter['invoice']:07d}"
        for line_no, amount in rows:
            self.files[upload]["invoices"].append(
                [number, code, when.isoformat(), str(line_no), money(amount)]
            )
            self.postings[(upload, code, line_no, "INVOICE")] += amount
            self.document_months[code].add(upload)
        self.stats["invoices"] += 1
        return number

    def _obligations(self, lines: list[Line], version: int, upload: str) -> list[Obligation]:
        amounts = allocate([(ln.no, ln.net, ln.ssp, ln.product.separate) for ln in lines])
        return [
            Obligation(
                ln.no,
                ln.product.method,
                ln.ssp,
                amounts[ln.no],
                ln.start,
                ln.end,
                ln.completion,
                [(when, fraction) for when, fraction, _ in ln.deliveries],
                version,
                upload,
            )
            for ln in lines
            if ln.product.separate
        ]

    def contract(self, index: int, customer: str) -> int:
        rng = self.rng
        self.postings = defaultdict(int)
        code = f"{index:09d}-INV_{106000000 + index}"
        booked = add_months(self.first, rng.randrange(self.booking_months))
        # D5: some contracts start before the month they are booked in, so they catch up.
        start_key = add_months(booked, -rng.choice([0, 0, 0, 0, 1, 2, 3]))
        wants_event = self.profile in ("events", "full") and rng.random() < (
            0.5 if self.profile == "events" else 0.25
        )
        term = rng.choice([12, 12, 12, 6, 3, 18, 1]) if not wants_event else rng.choice([12, 6, 18])
        lines = self._lines(start_key, term, code)
        event = rng.choice(["RENEWAL", "CANCELLATION", "UPGRADE"]) if wants_event else None

        if self.profile != "single" and event != "UPGRADE":
            self._add_deliveries(code, lines, booked)
        window = (min(ln.start for ln in lines), max(ln.end for ln in lines))
        self._write_version(code, customer, booked, "NEW", window[0], window, lines)
        for line in lines:
            for when, fraction, upload in line.deliveries:
                self.counter["delivery"] += 1
                self.files[upload]["deliveries"].append(
                    [
                        f"DEL-{self.counter['delivery']:07d}",
                        code,
                        str(line.no),
                        when.isoformat(),
                        f"{fraction / 1_000_000:.6f}",
                    ]
                )
                self.stats["deliveries"] += 1
                self.document_months[code].add(upload)

        obligations = self._obligations(lines, 1, booked)
        for po, line in zip(obligations, [ln for ln in lines if ln.product.separate], strict=True):
            self.allocation.append([code, str(line.no), "1", money(po.allocated)])
            po.earned = po.schedule()

        invoices = self._billing(code, lines, booked, event)
        credit_candidates = list(invoices)
        if event == "RENEWAL":
            self._renewal(code, customer, lines, booked, obligations, window)
        elif event == "CANCELLATION":
            self._cancellation(code, customer, lines, booked, obligations, window, invoices)
            credit_candidates = []
        elif event == "UPGRADE":
            self._upgrade(code, customer, lines, booked, obligations, window)

        self._record_revenue(code, obligations)
        if self.profile == "full" and credit_candidates and rng.random() < 0.2:
            self._goodwill_credit(code, credit_candidates)
        self._record_balances(code)
        self.all_postings.update(self.postings)
        return len(lines)

    def _billing(
        self, code: str, lines: list[Line], booked: str, event: str | None
    ) -> list[tuple[str, str, int]]:
        """Advance, late (unbilled first), instalments, or an invoice dated in a closed month."""
        rng = self.rng
        style = (
            "advance"
            if event == "CANCELLATION" or self.profile == "single"
            else rng.choice(["advance", "advance", "late", "instalments", "closed_month", "none"])
        )
        if event == "CANCELLATION" and rng.random() < 0.3:
            style = "none"
        rows = [(ln.no, ln.net) for ln in lines if ln.net > 0]
        total = sum(amount for _, amount in rows)
        if not rows or style == "none":
            return []
        made: list[tuple[str, str, int]] = []
        if style == "advance":
            when = month_start(booked).replace(day=rng.randint(1, 28))
            made.append((self._invoice(code, booked, when, rows), booked, total))
        elif style == "late":
            upload = add_months(booked, rng.randint(1, 4))
            when = month_start(upload).replace(day=rng.randint(1, 28))
            made.append((self._invoice(code, upload, when, rows), upload, total))
        elif style == "closed_month":
            upload = add_months(booked, rng.randint(1, 3))  # D6: posts in the month it arrives
            when = month_start(add_months(upload, -1)).replace(day=rng.randint(1, 28))
            made.append((self._invoice(code, upload, when, rows), upload, total))
            self.stats["late_invoices"] += 1
        else:
            parts = rng.randint(2, 3)
            each = total // parts
            for part in range(parts):
                amount = each if part < parts - 1 else total - each * (parts - 1)
                upload = add_months(booked, part * rng.randint(1, 3))
                when = month_start(upload).replace(day=rng.randint(1, 28))
                made.append(
                    (self._invoice(code, upload, when, [(rows[0][0], amount)]), upload, amount)
                )
        return made

    def _renewal(
        self,
        code: str,
        customer: str,
        lines: list[Line],
        booked: str,
        obligations: list[Obligation],
        window: tuple[date, date],
    ) -> None:
        """§5.5: a new term with all its lines, its own TP and allocation; old version untouched."""
        self.stats["renewals"] += 1
        start = window[1] + timedelta(days=1)
        # Everything for the old term arrives first: after a renewal, only the new term's lines
        # can be referenced, and the plan does not define old-term documents (see validation-log).
        earlier = self.document_months[code]
        upload = max(key_of(window[1]), add_months(booked, 1), *[add_months(m, 1) for m in earlier])
        # Monthly lines need a window of whole months, so the new term starts on the next 1st.
        start_key = key_of(start) if start.day == 1 else add_months(key_of(start), 1)
        new_lines = [
            self._line(ln.no, ln.product, start_key, 12) for ln in lines if ln.product.separate
        ]
        term = (min(ln.start for ln in new_lines), max(ln.end for ln in new_lines))
        self._write_version(code, customer, upload, "RENEWAL", term[0], term, new_lines)
        renewed = self._obligations(new_lines, 2, upload)
        for po in renewed:
            self.allocation.append([code, str(po.line_no), "2", money(po.allocated)])
            po.earned = po.schedule()
        obligations.extend(renewed)
        rows = [(ln.no, ln.net) for ln in new_lines if ln.net > 0]
        if rows:
            invoice_month = max(start_key, upload)
            self._invoice(code, invoice_month, month_start(invoice_month).replace(day=1), rows)

    def _cancellation(
        self,
        code: str,
        customer: str,
        lines: list[Line],
        booked: str,
        obligations: list[Obligation],
        window: tuple[date, date],
        invoices: list[tuple[str, str, int]],
    ) -> None:
        """§5.5: recognise through the date; monthly needs a month end; credit note for the rest."""
        self.stats["cancellations"] += 1
        rng = self.rng
        first = add_months(booked, 1)
        last = key_of(window[1])
        if first > last:
            first = last
        month = add_months(first, rng.randint(0, max(len(months(first, last)) - 1, 0)))
        has_monthly = any(ln.product.method == MONTHLY for ln in lines)
        when = (
            month_end(month) if has_monthly else month_start(month).replace(day=rng.randint(1, 28))
        )
        when = min(when, window[1]) if not has_monthly else when
        self._write_version(
            code, customer, month, "CANCELLATION", when, (window[0], max(window[1], when)), []
        )
        for po in obligations:
            po.earned = po.earned_through(when)
            po.live = False
        earned = sum(sum(po.earned.values()) for po in obligations)
        billed = sum(amount for _, upload, amount in invoices if upload <= month)
        residual = billed - earned
        if residual > 0 and invoices and invoices[0][1] < month:
            self._credit(code, invoices[0][0], month, month_end(month), residual, "Cancelled")

    def _upgrade(
        self,
        code: str,
        customer: str,
        lines: list[Line],
        booked: str,
        obligations: list[Obligation],
        window: tuple[date, date],
    ) -> None:
        """§5.5 and D8: pool of what is left plus the added price, shared by relative SSP."""
        self.stats["upgrades"] += 1
        rng = self.rng
        first = add_months(booked, 1)
        last = key_of(window[1])
        if first > last:
            first = last
        month = add_months(first, rng.randint(0, max(len(months(first, last)) - 1, 0)))
        has_monthly = any(ln.product.method == MONTHLY for ln in lines)
        effective = month_start(month)
        if not has_monthly:
            effective = effective.replace(day=rng.randint(1, 28))
        effective = min(effective, window[1]) if not has_monthly else effective
        no = max(ln.no for ln in lines) + 1
        added = self._line(no, rng.choice([p for p in RATABLE if p.method == DAILY]), month, 1)
        added.start, added.end = effective, window[1]
        self._write_version(code, customer, month, "UPGRADE", effective, window, [added])

        day_before = effective - timedelta(days=1)
        continuing: list[tuple[Obligation, int]] = []
        for po in obligations:
            if po.method == POINT:
                if (po.completion or po.end) < effective:
                    continue  # D8: satisfied
                continuing.append((po, po.ssp))
            elif po.end >= effective:
                remaining = (po.end - max(effective, po.start)).days + 1
                total = (po.end - po.start).days + 1
                continuing.append((po, half_up(Fraction(po.ssp * remaining, total))))

        earned = {id(po): po.earned_through(day_before) for po, _ in continuing}
        entries = [
            (po.line_no, po.allocated - sum(earned[id(po)].values()), basis, True)
            for po, basis in continuing
        ] + [(added.no, added.net, added.ssp, True)]
        amounts = allocate(entries)
        carried: list[Obligation] = []
        for po, basis in continuing:
            po.earned = earned[id(po)]
            po.live = False
            start = max(effective, po.start)
            new = Obligation(
                po.line_no,
                po.method,
                basis,
                amounts[po.line_no],
                start,
                po.end,
                po.completion,
                [],
                2,
                month,
            )
            new.earned = new.schedule()
            carried.append(new)
            self.allocation.append([code, str(po.line_no), "2", money(new.allocated)])
        new_po = Obligation(
            added.no, added.product.method, added.ssp, amounts[added.no], added.start, added.end,
            None, [], 2, month,
        )  # fmt: skip
        new_po.earned = new_po.schedule()
        self.allocation.append([code, str(added.no), "2", money(new_po.allocated)])
        obligations.extend([*carried, new_po])
        if added.net > 0:
            self._invoice(code, month, effective, [(added.no, added.net)])

    def _record_revenue(self, code: str, obligations: list[Obligation]) -> None:
        """§5.4: earned in a month, booked in that month or, if earlier, when it was uploaded."""
        for po in obligations:
            for service, cents in po.earned.items():
                if cents == 0:
                    continue
                self.schedule[(code, po.line_no, service)] += cents
                posting = max(service, po.earliest_posting)
                kind = "REVENUE_CATCH_UP" if service < posting else "REVENUE"
                self.postings[(posting, code, po.line_no, kind)] += cents
                self.last_period = max(self.last_period, posting)

    def _position_before_revenue(self, code: str, month: str) -> int:
        """Billed minus recognised when an upload in `month` is validated (§5.6)."""
        position = 0
        for (posting, contract, _, kind), cents in self.postings.items():
            if contract != code:
                continue
            credit = kind == "CREDIT_NOTE" and posting <= month
            revenue = kind.startswith("REVENUE") and posting < month
            if kind == "INVOICE" and posting <= month:
                position += cents
            elif credit or revenue:
                position -= cents
        return position

    def _credit(
        self, code: str, invoice: str, upload: str, when: date, cents: int, why: str
    ) -> None:
        self.counter["credit"] += 1
        self.files[upload]["credit_notes"].append(
            # Dated at month end and numbered to sort after INV-: §5.6 takes documents by date then
            # number, and a credit taken before the month's invoice is refused (E009).
            [f"NC-{self.counter['credit']:07d}", invoice, when.isoformat(), money(cents), why]
        )
        self.postings[(upload, code, 0, "CREDIT_NOTE")] += cents
        self.stats["credit_notes"] += 1

    def _goodwill_credit(self, code: str, invoices: list[tuple[str, str, int]]) -> None:
        """A credit on the unrecognised portion (§5.6), in a month with no other invoice."""
        invoice, invoice_month, total = invoices[0]
        month = add_months(invoice_month, self.rng.randint(1, 3))
        taken = {upload for _, upload, _ in invoices}
        if month in taken:
            return
        cents = min(total // 10, self._position_before_revenue(code, month))
        if cents <= 0:
            return
        self._credit(code, invoice, month, month_end(month), cents, "Goodwill")

    def _record_balances(self, code: str) -> None:
        """§5.6: the position at each month this contract touched, one row per month."""
        activity = sorted({k[0] for k in self.postings if k[1] == code})
        if not activity:
            return
        position = 0
        for period in months(activity[0], activity[-1]):
            for (posting, contract, _, kind), cents in self.postings.items():
                if contract != code or posting != period:
                    continue
                position += cents if kind == "INVOICE" else -cents
            if period in (activity[0], activity[-1]):
                self.balances.append(
                    [period, code, money(max(position, 0)), money(max(-position, 0))]
                )
        self.last_period = max(self.last_period, activity[-1])


def generate(
    out: Path,
    lines: int,
    seed: int,
    profile: str,
    first: str = "202501",
    booking_months: int = 12,
) -> dict[str, int]:
    """Write one case to `out`. Returns what it holds."""
    builder = Builder(seed, profile, first, booking_months)
    made, index = 0, 0
    customers: list[list[str]] = []
    while made < lines:
        index += 1
        if (index - 1) % 10 == 0:
            customers.append(
                [f"CUST-{len(customers) + 1:05d}", f"Customer {len(customers) + 1}", "GB"]
            )
        made += builder.contract(index, customers[-1][0])
    builder.stats["contracts"] = index
    builder.stats["lines"] = made

    for sub in ("inputs", "expected"):
        shutil.rmtree(out / sub, ignore_errors=True)
    builder.files[first]["customers"] = customers
    builder.files[first]["products"] = [
        [
            p.code,
            p.code,
            p.category,
            money(p.list_cents),
            p.source,
            money(p.ssp_cents) if p.ssp_cents is not None else "",
            str(p.pct) if p.pct is not None else "",
            p.method,
            "Y" if p.separate else "N",
            p.account,
            "2024-01-01",
        ]
        for p in CATALOGUE
    ]
    for period, files in builder.files.items():
        for name, rows in files.items():
            if rows:
                _write(out / "inputs" / period / f"{name}.csv", HEADERS[name], rows)
        builder.last_period = max(builder.last_period, period)

    expected = out / "expected"
    _write(
        expected / "allocation.csv",
        ["contract_id", "line_no", "version_no", "allocated_amount"],
        builder.allocation,
    )
    _write(
        expected / "schedule.csv",
        ["contract_id", "line_no", "service_period", "amount"],
        [[c, str(n), p, money(v)] for (c, n, p), v in sorted(builder.schedule.items())],
    )
    _write(
        expected / "postings.csv",
        ["posting_period", "contract_id", "line_no", "entry_type", "amount"],
        [[p, c, str(n), k, money(v)] for (p, c, n, k), v in sorted(builder.all_postings.items())],
    )
    _write(
        expected / "balances.csv",
        ["period", "contract_id", "deferred", "unbilled"],
        builder.balances,
    )
    meta = {
        "id": out.name,
        "level": "Generated",
        "description": f"{made} lines, profile {profile}, seed {seed}",
        "owner": "M2",
        "source": "tools/generate_dataset.py; expected values worked out without the engine",
        "open_period": first,
        "periods": {"from": first, "to": builder.last_period},
        "tolerance": "0.01",
        "status": "ready",
        "notes": ["Generated (P6-T1). Not an M1 hand calculation (plan §11.4)."],
    }
    (out / "case.yaml").write_text(yaml.safe_dump(meta, sort_keys=False), encoding="utf-8")
    return dict(builder.stats)


def _write(path: Path, header: list[str], rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lines", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument(
        "--profile", choices=["single", "bundles", "events", "full"], default="full"
    )
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    out = args.out or Path(f"../benchmarks/generated/{args.profile}_{args.lines}_s{args.seed}")
    stats = generate(out, args.lines, args.seed, args.profile)
    print(f"{out}: {stats}")


if __name__ == "__main__":
    main()
