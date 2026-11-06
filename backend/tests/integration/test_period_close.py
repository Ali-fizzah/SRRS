"""P5-T1, P5-T2, P5-T3: the checklist, close and reopen rules, and the reports (plan §5.8, §8)."""

import csv
import io
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import insert, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.auth.roles import Role
from app.models import (
    AccountingPeriod,
    AuditLog,
    JournalBatch,
    JournalEntry,
    JournalLine,
    ScheduleLine,
    UploadFile,
)
from app.models.enums import PeriodStatus, ScheduleLineStatus, UploadStatus, UploadTemplate
from app.services.journals import (
    JournalRuleError,
    approve_batch,
    generate_journals,
    post_batch,
    reverse_entry,
)
from app.services.period_close import (
    PeriodRuleError,
    build_checklist,
    close_period,
    gl_balances,
    reopen_period,
    start_close,
    sub_ledger_balances,
)
from app.services.recognition_run import run_recognition
from tests.benchmarks.runner import replay
from tests.integration.conftest import make_user, sign_in
from tests.integration.test_catch_up_and_billing import accepted, seed, upload
from tests.integration.test_events_and_journals import (
    YEAR,
    approver_id,  # noqa: F401  (fixture)
    book_month,
    new_contract,
    user_id,  # noqa: F401  (fixture)
)

REPO = Path(__file__).resolve().parents[3]
D = Decimal


def status_of(db: Session, key: str) -> PeriodStatus:
    status = db.scalar(select(AccountingPeriod.status).where(AccountingPeriod.period_key == key))
    assert status is not None
    return status


def items(db: Session, key: str = "202501") -> dict[str, str]:
    return {item.id: item.status for item in build_checklist(db, key).items}


def close_month(db: Session, key: str, uid: int, approver: int) -> None:
    start_close(db, key, uid)
    close_period(db, key, approver)


@pytest.fixture
def booked(db: Session, user_id: int, approver_id: int) -> int:  # noqa: F811
    contract_id = new_contract(
        db, user_id, "K", f"1,SUB,1,1200.00,,{YEAR},", invoices="I1,K,2025-01-01,1,1200.00"
    )
    book_month(db, user_id, approver_id, "202501")
    return contract_id


# --------------------------------------------------------------------------- checklist


def test_an_empty_month_passes_with_nothing_to_book(db: Session, user_id: int) -> None:  # noqa: F811
    run_recognition(db, user_id, period_key="202501")  # the fixture uploaded master data
    checklist = build_checklist(db, "202501")
    assert [i.status for i in checklist.items] == ["pass"] * 6
    assert not checklist.blocking


def test_each_step_of_the_month_turns_its_item_green(
    db: Session,
    user_id: int,  # noqa: F811
    approver_id: int,  # noqa: F811
) -> None:
    new_contract(
        db, user_id, "K", f"1,SUB,1,1200.00,,{YEAR},", invoices="I1,K,2025-01-01,1,1200.00"
    )
    assert items(db)["recognition"] == "fail"
    assert items(db)["batch"] == "fail"
    assert items(db)["posted"] == "fail"

    run_recognition(db, user_id, period_key="202501")
    assert items(db)["recognition"] == "pass"
    assert items(db)["batch"] == "fail"

    batch_id = generate_journals(db, "202501", user_id).batch_id
    assert batch_id is not None
    assert items(db)["batch"] == "pass"
    assert items(db)["posted"] == "fail"
    assert items(db)["tie_out"] == "fail"  # the GL holds posted lines only

    approve_batch(db, batch_id, approver_id)
    assert items(db)["posted"] == "fail"
    post_batch(db, batch_id, approver_id)
    assert items(db) == dict.fromkeys(
        ("uploads", "recognition", "batch", "tie_out", "warnings", "posted"), "pass"
    )


def test_an_upload_still_processing_blocks_the_close(db: Session, user_id: int) -> None:  # noqa: F811
    db.add(
        UploadFile(
            template=UploadTemplate.CONTRACTS,
            original_filename="x.csv",
            sha256="0" * 64,
            stored_path="(test)",
            uploaded_by=user_id,
            period_key="202501",
            status=UploadStatus.VALIDATING,
        )
    )
    db.flush()
    assert items(db)["uploads"] == "fail"


def test_data_after_the_last_run_fails_the_recognition_item(
    db: Session,
    user_id: int,  # noqa: F811
    approver_id: int,  # noqa: F811
    booked: int,
) -> None:
    assert items(db)["recognition"] == "pass"
    accepted(upload(db, user_id, invoices="I2,K,2025-01-20,1,10.00"))
    assert items(db)["recognition"] == "fail"
    run_recognition(db, user_id, period_key="202501")
    assert items(db)["recognition"] == "pass"
    assert items(db)["batch"] == "fail"  # the new invoice is in no batch
    book_month(db, user_id, approver_id, "202501")
    assert items(db)["batch"] == "pass" and items(db)["posted"] == "pass"


def test_tie_out_detects_a_difference_between_gl_and_sub_ledger(
    db: Session,
    booked: int,
) -> None:
    assert gl_balances(db, "202501") == sub_ledger_balances(db, "202501") == (110000, 0)
    # A schedule line booked without a journal: the sub-ledger moves, the GL does not.
    db.execute(
        update(ScheduleLine)
        .where(ScheduleLine.service_period == "202502")
        .values(posting_period="202501")
    )
    assert sub_ledger_balances(db, "202501") == (100000, 0)
    assert items(db)["tie_out"] == "fail"


def test_cancelled_with_deferred_left_warns_but_does_not_block(
    db: Session,
    user_id: int,  # noqa: F811
    approver_id: int,  # noqa: F811
) -> None:
    """D7."""
    new_contract(
        db, user_id, "K", f"1,SUB,1,1200.00,,{YEAR},", invoices="I1,K,2025-01-01,1,1200.00"
    )
    accepted(upload(db, user_id, contracts=f"K,C1,{YEAR},CANCELLATION,2025-01-31"))
    book_month(db, user_id, approver_id, "202501")
    checklist = build_checklist(db, "202501")
    warning = next(i for i in checklist.items if i.id == "warnings")
    assert warning.status == "warn" and "K" in warning.detail
    assert not checklist.blocking
    close_month(db, "202501", user_id, approver_id)


def test_an_event_that_could_not_apply_warns(
    db: Session,
    user_id: int,  # noqa: F811
    approver_id: int,  # noqa: F811
) -> None:
    new_contract(db, user_id, "K", f"1,DAILY,1,3650.00,,{YEAR},")
    book_month(db, user_id, approver_id, "202501")
    accepted(upload(db, user_id, contracts=f"K,C1,{YEAR},CANCELLATION,2025-01-10"))
    run_recognition(db, user_id, period_key="202501")
    warning = next(i for i in build_checklist(db, "202501").items if i.id == "warnings")
    assert warning.status == "warn" and "not applied" in warning.detail


def test_a_reversal_moving_the_split_warns_but_the_total_ties(
    db: Session,
    user_id: int,  # noqa: F811
    approver_id: int,  # noqa: F811
    booked: int,
) -> None:
    entry = db.scalar(select(JournalEntry.id).where(JournalEntry.entry_type == "INVOICE"))
    assert entry is not None
    batch = reverse_entry(db, entry, user_id, "Wrong customer")
    approve_batch(db, batch.id, approver_id)
    post_batch(db, batch.id, approver_id)
    # GL deferred is -100.00; the sub-ledger shows that position as 100.00 unbilled.
    assert items(db)["tie_out"] == "warn"
    assert not build_checklist(db, "202501").blocking


# --------------------------------------------------------------------------- close


def test_close_moves_the_period_on_and_writes_the_audit_log(
    db: Session,
    user_id: int,  # noqa: F811
    approver_id: int,  # noqa: F811
    booked: int,
) -> None:
    close_month(db, "202501", user_id, approver_id)
    assert status_of(db, "202501") == PeriodStatus.CLOSED
    assert status_of(db, "202502") == PeriodStatus.OPEN
    period = db.scalar(select(AccountingPeriod).where(AccountingPeriod.period_key == "202501"))
    assert period is not None and period.closed_by == approver_id and period.closed_at is not None
    logged = set(db.scalars(select(AuditLog.action)))
    assert {"PERIOD_CLOSE_STARTED", "PERIOD_CLOSED"} <= logged


def test_close_needs_closing_first_and_start_close_needs_open(
    db: Session,
    user_id: int,  # noqa: F811
    approver_id: int,  # noqa: F811
) -> None:
    with pytest.raises(PeriodRuleError, match="not CLOSING"):
        close_period(db, "202501", approver_id)
    start_close(db, "202501", user_id)
    with pytest.raises(PeriodRuleError, match="not OPEN"):
        start_close(db, "202501", user_id)


def test_close_is_refused_while_an_item_fails(
    db: Session,
    user_id: int,  # noqa: F811
    approver_id: int,  # noqa: F811
) -> None:
    new_contract(db, user_id, "K", f"1,SUB,1,1200.00,,{YEAR},")
    run_recognition(db, user_id, period_key="202501")
    start_close(db, "202501", user_id)
    with pytest.raises(PeriodRuleError) as refused:
        close_period(db, "202501", approver_id)
    assert refused.value.code == "CHECKLIST_NOT_PASSED"
    assert status_of(db, "202501") == PeriodStatus.CLOSING
    assert status_of(db, "202502") == PeriodStatus.FUTURE


def test_journals_can_still_be_generated_during_closing(
    db: Session,
    user_id: int,  # noqa: F811
    approver_id: int,  # noqa: F811
) -> None:
    """§5.8: journals are generated during close."""
    new_contract(db, user_id, "K", f"1,SUB,1,1200.00,,{YEAR},")
    run_recognition(db, user_id, period_key="202501")
    start_close(db, "202501", user_id)
    batch_id = generate_journals(db, "202501", user_id).batch_id
    assert batch_id is not None
    approve_batch(db, batch_id, approver_id)
    post_batch(db, batch_id, approver_id)
    close_period(db, "202501", approver_id)


# --------------------------------------------------------------------------- C01


def test_c01_closed_january_cannot_be_changed(
    db: Session,
    user_id: int,  # noqa: F811
    approver_id: int,  # noqa: F811
    booked: int,
) -> None:
    close_month(db, "202501", user_id, approver_id)

    savepoint = db.begin_nested()
    with pytest.raises(DBAPIError, match="POSTED"):
        db.execute(update(JournalLine).values(debit=D("1.00")))
    savepoint.rollback()

    savepoint = db.begin_nested()
    with pytest.raises(DBAPIError, match="POSTED"):
        db.execute(
            update(ScheduleLine)
            .where(ScheduleLine.status == ScheduleLineStatus.POSTED)
            .values(amount=D("1.00"))
        )
    savepoint.rollback()

    january = db.scalar(select(AccountingPeriod.id).where(AccountingPeriod.period_key == "202501"))
    savepoint = db.begin_nested()
    with pytest.raises(DBAPIError, match="CLOSED"):
        db.execute(insert(JournalBatch).values(period_id=january, batch_no=9, generated_by=user_id))
    savepoint.rollback()


def test_a_batch_cannot_be_approved_once_its_period_is_not_current(
    db: Session,
    user_id: int,  # noqa: F811
    approver_id: int,  # noqa: F811
) -> None:
    """Close refuses unposted batches, so this is the reopen path: February's draft goes FUTURE."""
    new_contract(db, user_id, "K", f"1,SUB,1,1200.00,,{YEAR},")
    book_month(db, user_id, approver_id, "202501")
    close_month(db, "202501", user_id, approver_id)
    run_recognition(db, user_id, period_key="202502")
    draft = generate_journals(db, "202502", user_id).batch_id
    assert draft is not None
    reopen_period(db, "202501", approver_id, "Late correction")
    assert status_of(db, "202502") == PeriodStatus.FUTURE
    with pytest.raises(JournalRuleError) as refused:
        approve_batch(db, draft, approver_id)
    assert refused.value.code == "PERIOD_NOT_CURRENT"


# --------------------------------------------------------------------------- reopen


def test_reopen_returns_the_latest_period_and_writes_the_reason(
    db: Session,
    user_id: int,  # noqa: F811
    approver_id: int,  # noqa: F811
    booked: int,
) -> None:
    close_month(db, "202501", user_id, approver_id)
    reopen_period(db, "202501", approver_id, "Wrong invoice")
    assert status_of(db, "202501") == PeriodStatus.OPEN
    assert status_of(db, "202502") == PeriodStatus.FUTURE
    reason = db.scalar(select(AuditLog.reason).where(AuditLog.action == "PERIOD_REOPENED"))
    assert reason == "Wrong invoice"


def test_only_the_latest_closed_period_can_reopen(
    db: Session,
    user_id: int,  # noqa: F811
    approver_id: int,  # noqa: F811
) -> None:
    run_recognition(db, user_id, period_key="202501")  # the fixture uploaded master data
    close_month(db, "202501", user_id, approver_id)
    close_month(db, "202502", user_id, approver_id)
    with pytest.raises(PeriodRuleError) as older:
        reopen_period(db, "202501", approver_id, "Too old")
    assert older.value.code == "NOT_LATEST_CLOSED"
    with pytest.raises(PeriodRuleError):
        reopen_period(db, "202503", approver_id, "Not closed")


def test_reopen_refused_when_the_next_period_has_a_posted_batch(
    db: Session,
    user_id: int,  # noqa: F811
    approver_id: int,  # noqa: F811
    booked: int,
) -> None:
    close_month(db, "202501", user_id, approver_id)
    book_month(db, user_id, approver_id, "202502")
    with pytest.raises(PeriodRuleError) as refused:
        reopen_period(db, "202501", approver_id, "Too late")
    assert refused.value.code == "NEXT_PERIOD_HAS_POSTED_BATCH"
    assert status_of(db, "202501") == PeriodStatus.CLOSED


# --------------------------------------------------------------------------- API


@pytest.fixture
def api(client: TestClient, db: Session, user_id: int) -> TestClient:  # noqa: F811
    admin = make_user(db, [Role.ADMIN])
    sign_in(client, admin)
    return client


def test_close_workflow_through_the_api(
    api: TestClient,
    db: Session,
    booked: int,
) -> None:
    listed = api.get("/api/v1/periods/202501/checklist").json()
    assert listed["can_close"] is True and len(listed["items"]) == 6
    assert api.post("/api/v1/periods/202501/close").status_code == 409
    assert api.post("/api/v1/periods/202501/start-close").json()["status"] == "CLOSING"
    uploaded = api.post(
        "/api/v1/uploads", files=[("files", ("contracts.csv", b"contract_id", "text/csv"))]
    )
    assert uploaded.status_code == 409  # §5.8: CLOSING blocks new uploads
    assert api.post("/api/v1/periods/202501/close").json()["status"] == "CLOSED"
    assert api.get("/api/v1/periods?status=OPEN").json()["items"][0]["period_key"] == "202502"
    assert api.post("/api/v1/periods/202501/reopen", json={}).status_code == 422
    assert api.post("/api/v1/periods/202501/reopen", json={"reason": "Fix"}).status_code == 200


def test_close_refusal_says_why(
    api: TestClient,
    db: Session,
    user_id: int,  # noqa: F811
) -> None:
    new_contract(db, user_id, "K", f"1,SUB,1,1200.00,,{YEAR},")
    run_recognition(db, user_id, period_key="202501")
    api.post("/api/v1/periods/202501/start-close")
    response = api.post("/api/v1/periods/202501/close")
    assert response.status_code == 409
    body = response.json()["error"]
    assert body["code"] == "CHECKLIST_NOT_PASSED"
    assert {"batch", "posted"} <= {item["id"] for item in body["details"]}


def csv_rows(response: Any) -> list[dict[str, str]]:
    assert response.status_code == 200
    return list(csv.DictReader(io.StringIO(response.text)))


def test_reports_show_the_booked_month(
    api: TestClient,
    db: Session,
    user_id: int,  # noqa: F811
    approver_id: int,  # noqa: F811
    booked: int,
) -> None:
    schedule = api.get("/api/v1/reports/revenue-schedule").json()
    assert schedule["total"] == 12 and schedule["total_amount"] == "1200.00"
    assert schedule["items"][0]["customer_name"] == "Acme"
    assert api.get("/api/v1/reports/revenue-schedule?contract=NOPE").json()["total"] == 0
    assert api.get("/api/v1/reports/revenue-schedule?status=POSTED").json()["total"] == 1
    assert api.get("/api/v1/reports/revenue-schedule?product=SUB").json()["total"] == 12
    assert api.get("/api/v1/reports/revenue-schedule?period_to=202503").json()["total"] == 3

    rollforward = api.get("/api/v1/reports/deferred-rollforward").json()["items"]
    assert [row["period"] for row in rollforward] == ["202501"]
    january = rollforward[0]
    assert (january["billings"], january["recognised"], january["closing_deferred"]) == (
        "1200.00",
        "100.00",
        "1100.00",
    )

    trend = api.get("/api/v1/reports/recognized-vs-deferred").json()["items"]
    assert trend[0]["recognised"] == "100.00" and trend[0]["deferred"] == "1100.00"

    register = api.get("/api/v1/reports/journal-register").json()
    assert register["total"] == 4
    assert register["items"][0]["customer_name"] == "Acme"
    assert api.get("/api/v1/reports/journal-register?account=4100").json()["total"] == 1
    assert api.get("/api/v1/reports/journal-register?entry_type=INVOICE").json()["total"] == 2

    summary = {r["account_code"]: r for r in api.get("/api/v1/reports/gl-summary").json()["items"]}
    assert summary["1100"]["debit"] == "1200.00" and summary["1100"]["net"] == "1200.00"
    assert summary["2400"]["net"] == "-1100.00"
    assert summary["4100"]["credit"] == "100.00"

    mrr = api.get("/api/v1/reports/mrr-arr").json()["items"]
    assert len(mrr) == 12 and mrr[0]["mrr"] == "100.00" and mrr[0]["arr"] == "1200.00"

    status = api.get("/api/v1/reports/close-status?period_to=202502").json()
    assert status["items"][0]["status"] == "OPEN" and status["items"][0]["posted_batches"] == 1
    assert status["current"]["period_key"] == "202501"
    assert status["current"]["can_close"] is True


def test_rollforward_carries_a_balance_through_an_idle_month(
    api: TestClient,
    db: Session,
    user_id: int,  # noqa: F811
    approver_id: int,  # noqa: F811
) -> None:
    """February has no activity at all: nothing is earned until the March completion."""
    new_contract(
        db,
        user_id,
        "K",
        "1,PRINT,1,500.00,,2025-01-01,2025-03-31,2025-03-31",
        invoices="I1,K,2025-01-01,1,500.00",
    )
    for period in ("202501", "202502", "202503"):
        book_month(db, user_id, approver_id, period)
        close_month(db, period, user_id, approver_id)
    rows = api.get("/api/v1/reports/deferred-rollforward").json()["items"]
    assert [r["period"] for r in rows] == ["202501", "202502", "202503"]
    assert (rows[1]["opening_deferred"], rows[1]["closing_deferred"]) == ("500.00", "500.00")
    assert (rows[2]["recognised"], rows[2]["closing_deferred"]) == ("500.00", "0.00")


def test_rollforward_drills_down_to_contracts(
    api: TestClient,
    db: Session,
    user_id: int,  # noqa: F811
    approver_id: int,  # noqa: F811
    booked: int,
) -> None:
    other = new_contract(db, user_id, "L", f"1,SUB,1,1200.00,,{YEAR},")
    book_month(db, user_id, approver_id, "202501")
    url = "/api/v1/reports/deferred-rollforward?group_by=contract"
    assert api.get(url).status_code == 422
    rows = api.get(f"{url}&period_from=202501&period_to=202501").json()["items"]
    assert {r["contract_code"]: r["closing_deferred"] for r in rows} == {
        "K": "1100.00",
        "L": "0.00",
    }
    assert {r["contract_code"]: r["closing_unbilled"] for r in rows}["L"] == "100.00"
    assert {r["contract_id"] for r in rows} == {booked, other}
    only_k = api.get(f"{url}&period_from=202501&period_to=202501&contract=K").json()["items"]
    assert [r["contract_code"] for r in only_k] == ["K"]


def test_validation_log_lists_errors_and_filters_by_code(
    api: TestClient,
    db: Session,
    user_id: int,  # noqa: F811
) -> None:
    upload(db, user_id, customers="C2,Bad,TOOLONG")
    upload(db, user_id, contracts=f"Z,NOPE,{YEAR},NEW,2025-01-01")
    log = api.get("/api/v1/reports/validation-log").json()
    assert log["total"] >= 2
    code = log["items"][0]["error_code"]
    filtered = api.get(f"/api/v1/reports/validation-log?code={code}").json()
    assert filtered["total"] >= 1 and all(r["error_code"] == code for r in filtered["items"])
    assert api.get("/api/v1/reports/validation-log?code=NOPE").status_code == 422


def test_an_uploader_reads_the_validation_log_but_no_other_report(
    client: TestClient,
    db: Session,
    user_id: int,  # noqa: F811
) -> None:
    sign_in(client, make_user(db, [Role.UPLOADER]))
    assert client.get("/api/v1/reports/validation-log").status_code == 200
    assert client.get("/api/v1/reports/gl-summary").status_code == 403


def test_a_bad_sort_is_refused_on_computed_reports(api: TestClient, booked: int) -> None:
    response = api.get("/api/v1/reports/deferred-rollforward?sort=password")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_SORT"
    ascending = api.get("/api/v1/reports/mrr-arr?sort=-period").json()["items"]
    assert ascending[0]["period"] == "202512"


def test_csv_of_the_revenue_schedule_has_every_row(api: TestClient, booked: int) -> None:
    """P5-T3: more rows than one page, and CSV still returns them all."""
    paged = api.get("/api/v1/reports/revenue-schedule?page_size=5").json()
    assert len(paged["items"]) == 5
    rows = csv_rows(api.get("/api/v1/reports/revenue-schedule?page_size=5&format=csv"))
    assert len(rows) == paged["total"] == 12
    assert rows[0]["contract_code"] == "K" and rows[0]["amount"] == "100.00"


def test_every_report_exports_csv(api: TestClient, booked: int) -> None:
    for name in (
        "deferred-rollforward",
        "recognized-vs-deferred",
        "journal-register",
        "gl-summary",
        "mrr-arr",
        "close-status",
        "validation-log",
    ):
        response = api.get(f"/api/v1/reports/{name}?format=csv")
        assert response.status_code == 200, name
        assert response.headers["content-type"].startswith("text/csv"), name


def test_x02_revenue_schedule_csv_matches_the_workbook_row_count(
    api: TestClient,
    db: Session,
) -> None:
    """P5-T3 acceptance: replay X02, and the CSV has one row per schedule line."""
    result = replay(db, REPO / "benchmarks" / "cases" / "X02_revrec_mock_data", seed, make_user)
    assert result.passed
    live = db.scalars(
        select(ScheduleLine.id).where(ScheduleLine.status != ScheduleLineStatus.SUPERSEDED)
    ).all()
    rows = csv_rows(api.get("/api/v1/reports/revenue-schedule?format=csv"))
    assert len(rows) == len(live) > 200
    assert sum(D(r["amount"]) for r in rows) == sum(
        db.scalars(
            select(ScheduleLine.amount).where(ScheduleLine.status != ScheduleLineStatus.SUPERSEDED)
        )
    )
