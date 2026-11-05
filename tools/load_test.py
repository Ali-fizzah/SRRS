"""Load test L01 (plan §11.3, tasks P7-T1, P7-T2). `make load N=50000`.

Times upload, recognition and journals on a generated dataset, then checks the amounts are still
right, because a fast wrong answer is no use. It uses its own database, `revrec_load`, which it
drops and recreates each time; it never touches development data.

Targets: engine under 60 seconds, the whole run under 5 minutes.
"""

import argparse
import cProfile
import csv
import pstats
import sys
import time
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from generate_dataset import generate  # noqa: E402
from seed import seed_accounts, seed_gl_mappings, seed_periods  # noqa: E402
from sqlalchemy import create_engine, func, select, text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

from app.auth.passwords import hash_password  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.ingestion.loader import load_upload  # noqa: E402
from app.ingestion.templates import TEMPLATES  # noqa: E402
from app.models import (  # noqa: E402
    Contract,
    ContractLine,
    ContractVersion,
    JournalBatch,
    JournalLine,
    PerformanceObligation,
    RevenueSchedule,
    ScheduleLine,
    UploadFile,
    User,
)
from app.models.enums import ScheduleLineStatus, UploadTemplate  # noqa: E402
from app.services.journals import approve_batch, generate_journals, post_batch  # noqa: E402
from app.services.period_close import build_checklist  # noqa: E402
from app.services.recognition_run import run_recognition  # noqa: E402

DATABASE = "revrec_load"
ENGINE_TARGET_SECONDS = 60
TOTAL_TARGET_SECONDS = 300
FIRST_PERIOD = "202501"


def _fresh_database() -> str:
    """Drop and recreate the load database only, then migrate it."""
    url = make_url(get_settings().database_url).set(database=DATABASE)
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        # The name is the constant above, never user input.
        conn.execute(text(f'DROP DATABASE IF EXISTS "{DATABASE}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{DATABASE}"'))
    admin.dispose()
    rendered = url.render_as_string(hide_password=False)
    config = Config()
    config.set_main_option("script_location", str(Path.cwd() / "alembic"))
    config.set_main_option("sqlalchemy.url", rendered.replace("%", "%%"))
    command.upgrade(config, "head")
    return rendered


class Timer:
    def __init__(self) -> None:
        self.rows: list[tuple[str, float]] = []

    def run(self, name: str, work, profile: bool = False):  # type: ignore[no-untyped-def]
        started = time.perf_counter()
        profiler = cProfile.Profile() if profile else None
        result = profiler.runcall(work) if profiler else work()
        seconds = time.perf_counter() - started
        self.rows.append((name, seconds))
        print(f"  {name:<34}{seconds:>9.1f} s", flush=True)
        if profiler:
            stats = pstats.Stats(profiler).sort_stats("cumulative")
            stats.print_stats(22)
            stats.sort_stats("tottime").print_stats(22)
        return result


def _upload(db: Session, folder: Path, period: str, user_id: int) -> list:
    order = list(TEMPLATES)
    batch = []
    for path in sorted(folder.glob("*.csv"), key=lambda p: order.index(UploadTemplate(p.stem))):
        record = UploadFile(
            template=UploadTemplate(path.stem),
            original_filename=path.name,
            sha256="0" * 64,
            stored_path=str(path),
            uploaded_by=user_id,
            period_key=period,
        )
        db.add(record)
        batch.append((record, path.read_bytes()))
    db.flush()
    return load_upload(db, batch, user_id)


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _verify(db: Session, case: Path) -> list[str]:
    """Compare with the generator's own answers: every allocation, and every schedule's total."""
    problems = []
    expected_alloc = {
        (r["contract_id"], r["line_no"], r["version_no"]): Decimal(r["allocated_amount"])
        for r in _read(case / "expected" / "allocation.csv")
    }
    actual_alloc = {
        (code, str(line_no), str(version_no)): amount
        for code, line_no, version_no, amount in db.execute(
            select(
                Contract.contract_code,
                ContractLine.line_no,
                ContractVersion.version_no,
                PerformanceObligation.allocated_amount,
            )
            .join(ContractLine, ContractLine.id == PerformanceObligation.contract_line_id)
            .join(ContractVersion, ContractVersion.id == PerformanceObligation.contract_version_id)
            .join(Contract, Contract.id == ContractVersion.contract_id)
        ).tuples()
    }
    wrong = [key for key in expected_alloc if expected_alloc[key] != actual_alloc.get(key)]
    if wrong or len(actual_alloc) != len(expected_alloc):
        problems.append(f"{len(wrong)} allocations differ, e.g. {wrong[:3]}")

    # Every obligation's schedule must total exactly its allocation (plan §11.1). Row by row is
    # for the replay: deliveries uploaded in later months move amounts between periods.
    scheduled = {
        (code, str(line_no)): amount
        for code, line_no, amount in db.execute(
            select(Contract.contract_code, ContractLine.line_no, func.sum(ScheduleLine.amount))
            .join(RevenueSchedule, RevenueSchedule.id == ScheduleLine.schedule_id)
            .join(
                PerformanceObligation,
                PerformanceObligation.id == RevenueSchedule.performance_obligation_id,
            )
            .join(ContractLine, ContractLine.id == PerformanceObligation.contract_line_id)
            .join(ContractVersion, ContractVersion.id == RevenueSchedule.contract_version_id)
            .join(Contract, Contract.id == ContractVersion.contract_id)
            .where(ScheduleLine.status != ScheduleLineStatus.SUPERSEDED)
            .group_by(Contract.contract_code, ContractLine.line_no)
        ).tuples()
    }
    off = [key for key, amount in actual_alloc.items() if scheduled.get(key[:2]) != amount]
    if off:
        problems.append(f"{len(off)} schedules do not total their allocation, e.g. {off[:3]}")
    debit, credit = db.execute(
        select(func.coalesce(func.sum(JournalLine.debit), 0), func.sum(JournalLine.credit))
    ).one()
    if debit != credit:
        problems.append(f"journals do not balance: {debit} vs {credit}")
    print(
        f"  checked {len(actual_alloc)} allocations and {len(scheduled)} schedule totals; "
        f"debits = credits = {debit}"
    )
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lines", type=int, default=50_000)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--profile", default="bundles")
    parser.add_argument("--profile-stage", default=None, help="print a profile of this stage")
    args = parser.parse_args()

    timer = Timer()
    case = Path("../benchmarks/generated") / f"load_{args.lines}_s{args.seed}"
    print(f"Load test: {args.lines} lines, profile {args.profile}, seed {args.seed}", flush=True)
    stats = timer.run(
        "generate files (not counted)",
        lambda: generate(case, args.lines, args.seed, args.profile, booking_months=1),
    )
    print(f"  dataset: {stats}", flush=True)
    url = timer.run("create database (not counted)", _fresh_database)
    engine = create_engine(url)
    factory = sessionmaker(engine)
    profile = args.profile_stage

    with factory() as db:
        seed_accounts(db)
        seed_gl_mappings(db)
        seed_periods(db, FIRST_PERIOD)
        users = []
        for email in ("acct@load.local", "appr@load.local"):
            user = User(email=email, full_name=email, password_hash=hash_password("Load-Test-1234"))
            db.add(user)
            users.append(user)
        db.commit()
        accountant, approver = users[0].id, users[1].id

    counted_from = len(timer.rows)
    folder = case / "inputs" / FIRST_PERIOD

    def stage(name: str, work):  # type: ignore[no-untyped-def]
        with factory() as db:
            result = timer.run(name, lambda: work(db), profile == name)
            db.commit()
        return result

    summaries = stage("upload", lambda db: _upload(db, folder, FIRST_PERIOD, accountant))
    rejected = sum(s.rejected_rows for s in summaries)
    recognition = stage(
        "recognition",
        lambda db: run_recognition(db, accountant, period_key=FIRST_PERIOD, commit_every=2000),
    )
    journals = stage("journals", lambda db: generate_journals(db, FIRST_PERIOD, accountant))
    counted = timer.rows[counted_from:]
    total = sum(seconds for _, seconds in counted)

    if journals.batch_id is not None:
        stage(
            "approve and post (extra)",
            lambda db: (
                approve_batch(db, journals.batch_id, approver),
                post_batch(db, journals.batch_id, approver),
            ),
        )
    stage("close checklist (extra)", lambda db: build_checklist(db, FIRST_PERIOD))

    with factory() as db:
        lines = db.scalar(select(func.count()).select_from(ContractLine))
        problems = _verify(db, case)
        batches = db.scalar(select(func.count()).select_from(JournalBatch))
    engine.dispose()

    engine_seconds = dict(counted)["recognition"]
    print()
    print(f"Lines loaded: {lines}; rows rejected: {rejected}; batches: {batches}")
    print(f"Recognition: {recognition.schedule_lines_created} schedule lines")
    print(f"Skipped: {len(recognition.skipped)} recognition, {len(journals.skipped)} journals")
    print(f"Engine:  {engine_seconds:7.1f} s  (target {ENGINE_TARGET_SECONDS} s)")
    print(
        f"Total:   {total:7.1f} s  (target {TOTAL_TARGET_SECONDS} s; upload+recognition+journals)"
    )
    passed = (
        engine_seconds < ENGINE_TARGET_SECONDS
        and total < TOTAL_TARGET_SECONDS
        and not problems
        and rejected == 0
        and not recognition.skipped
        and not journals.skipped
    )
    for problem in problems:
        print(f"PROBLEM: {problem}")
    print("RESULT: " + ("PASS" if passed else "FAIL"))

    report = Path("../benchmarks/reports")
    report.mkdir(parents=True, exist_ok=True)
    with (report / "load.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(["stage", "seconds"])
        writer.writerows((name, f"{seconds:.1f}") for name, seconds in timer.rows)
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
