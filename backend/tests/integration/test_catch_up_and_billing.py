"""P3-T4, P3-T5, P3-T6: catch-up, late deliveries, balances and contract detail endpoints."""

import importlib.util
import sys
from decimal import Decimal
from pathlib import Path
from types import ModuleType

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.auth.roles import Role
from app.ingestion.loader import UploadSummary, load_upload
from app.ingestion.templates import TEMPLATES
from app.models import (
    AccountingPeriod,
    Contract,
    ScheduleLine,
    UploadFile,
    ValidationError,
)
from app.models.enums import PeriodStatus, ScheduleLineStatus, UploadTemplate
from app.services.billing import balance_at, contract_balances
from app.services.recognition_run import run_recognition
from tests.integration.conftest import make_user, sign_in

REPO = Path(__file__).resolve().parents[3]

PRODUCTS = (
    "SUB,Subscription,,1200.00,LIST_PRICE,,,RATABLE_MONTHLY,Y,4100,\n"
    "DAILY,Daily,,1000.00,LIST_PRICE,,,RATABLE_DAILY,Y,4100,\n"
    "PRINT,Print,,300.00,LIST_PRICE,,,POINT_IN_TIME,Y,4200,\n"
    "SETUP,Setup,,500.00,LIST_PRICE,,,POINT_IN_TIME,N,4300,"
)


def _seed_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("seed", REPO / "tools" / "seed.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


seed = _seed_module()


def upload(db: Session, user_id: int, **files: str) -> list[UploadSummary]:
    period = db.scalar(
        select(AccountingPeriod.period_key).where(AccountingPeriod.status == PeriodStatus.OPEN)
    )
    assert period is not None
    batch = []
    for name, body in files.items():
        template = TEMPLATES[UploadTemplate(name)]
        record = UploadFile(
            template=template.name,
            original_filename=f"{name}.csv",
            sha256="0" * 64,
            stored_path="(test)",
            uploaded_by=user_id,
            period_key=period,
        )
        db.add(record)
        batch.append((record, (",".join(template.headers) + "\n" + body.strip() + "\n").encode()))
    db.flush()
    return load_upload(db, batch, user_id)


def accepted(summaries: list[UploadSummary]) -> None:
    assert all(s.status == "ACCEPTED" for s in summaries), summaries


def next_month(db: Session) -> str:
    """Close the OPEN period and open the next, as the close workflow will (task P5-T1)."""
    current = db.scalar(
        select(AccountingPeriod.period_key).where(AccountingPeriod.status == PeriodStatus.OPEN)
    )
    assert current is not None
    following = f"{int(current[:4]) + 1}01" if current.endswith("12") else str(int(current) + 1)
    db.execute(
        update(AccountingPeriod)
        .where(AccountingPeriod.period_key == current)
        .values(status=PeriodStatus.CLOSED)
    )
    db.execute(
        update(AccountingPeriod)
        .where(AccountingPeriod.period_key == following)
        .values(status=PeriodStatus.OPEN)
    )
    return following


@pytest.fixture
def user_id(db: Session) -> int:
    seed.seed_accounts(db)
    seed.seed_periods(db, "202507")
    uid = make_user(db, [Role.ACCOUNTANT]).id
    accepted(upload(db, uid, products=PRODUCTS, customers="C1,Acme,GB"))
    return uid


@pytest.fixture
def api(client: TestClient, db: Session, user_id: int) -> TestClient:
    sign_in(client, make_user(db, [Role.UPLOADER]))
    return client


def contract(db: Session, user_id: int, code: str, *lines: str) -> None:
    accepted(
        upload(
            db,
            user_id,
            contracts=f"{code},C1,2025-01-01,2027-12-31,NEW,2025-01-01",
            contract_lines="\n".join(f"{code},{line}" for line in lines),
        )
    )


def lines_of(db: Session) -> list[tuple[str, str, str | None, bool, Decimal]]:
    rows = db.execute(
        select(
            ScheduleLine.service_period,
            ScheduleLine.status,
            ScheduleLine.posting_period,
            ScheduleLine.is_catch_up,
            ScheduleLine.amount,
        ).order_by(ScheduleLine.service_period, ScheduleLine.id)
    ).all()
    return [(s, st.value, p, c, a) for s, st, p, c, a in rows]


def contract_id(db: Session, code: str) -> int:
    found = db.scalar(select(Contract.id).where(Contract.contract_code == code))
    assert found is not None
    return found


# --------------------------------------------------------------------------- P3-T4 catch-up


def test_contract_booked_late_gets_catch_up_then_current_then_future(
    db: Session, user_id: int
) -> None:
    """§5.4: booked in Jul 2025, ratable Jan-Dec: Jan-Jun catch-up, Jul current, later waits."""
    contract(db, user_id, "K", "1,SUB,1,1200.00,,2025-01-01,2025-12-31,")
    summary = run_recognition(db, user_id)
    assert (summary.lines_booked, summary.catch_up_lines) == (7, 6)
    lines = lines_of(db)
    assert [(p, c) for _, _, p, c, _ in lines[:6]] == [("202507", True)] * 6
    assert lines[6][2:4] == ("202507", False)  # July itself
    assert all(p is None and c is False for _, _, p, c, _ in lines[7:])


def test_next_month_books_only_that_month_and_keeps_earlier_periods(
    db: Session, user_id: int
) -> None:
    contract(db, user_id, "K", "1,SUB,1,1200.00,,2025-01-01,2025-12-31,")
    run_recognition(db, user_id)
    next_month(db)
    summary = run_recognition(db, user_id)
    assert (summary.lines_booked, summary.catch_up_lines) == (1, 0)
    lines = {service: (posting, catch_up) for service, _, posting, catch_up, _ in lines_of(db)}
    assert lines["202501"] == ("202507", True)  # a line keeps the period it was booked in
    assert lines["202508"] == ("202508", False)
    assert lines["202509"] == (None, False)


def test_running_again_in_the_same_month_books_nothing_more(db: Session, user_id: int) -> None:
    contract(db, user_id, "K", "1,SUB,1,1200.00,,2025-01-01,2025-12-31,")
    run_recognition(db, user_id)
    again = run_recognition(db, user_id)
    assert (again.lines_booked, again.catch_up_lines, again.schedules_rebuilt) == (0, 0, 0)


def test_run_for_an_explicit_period_during_close(db: Session, user_id: int) -> None:
    """During CLOSING no period is OPEN, but the job names the period (§5.8)."""
    contract(db, user_id, "K", "1,SUB,1,1200.00,,2025-01-01,2025-12-31,")
    db.execute(
        update(AccountingPeriod)
        .where(AccountingPeriod.period_key == "202507")
        .values(status=PeriodStatus.CLOSING)
    )
    assert run_recognition(db, user_id, period_key="202507").lines_booked == 7


# --------------------------------------------------------------------------- D3 late deliveries


def test_delivery_uploaded_later_replaces_the_unbooked_remainder(db: Session, user_id: int) -> None:
    """D3: 300.00 due at completion in 2027; a 25% delivery arrives in August 2025."""
    contract(db, user_id, "K", "1,PRINT,1,300.00,,2025-01-01,2027-12-31,")
    run_recognition(db, user_id)
    assert [(s, a) for s, _, _, _, a in lines_of(db)] == [("202712", Decimal("300.00"))]

    next_month(db)
    accepted(upload(db, user_id, deliveries="D1,K,1,2025-03-31,0.25"))
    summary = run_recognition(db, user_id)
    assert summary.schedules_rebuilt == 1
    lines = lines_of(db)
    assert ("202503", "PENDING", "202508", True, Decimal("75.00")) in lines  # catch-up
    assert ("202712", "SUPERSEDED", None, False, Decimal("300.00")) in lines  # kept as history
    assert ("202712", "PENDING", None, False, Decimal("225.00")) in lines
    active = [a for _, status, _, _, a in lines if status != "SUPERSEDED"]
    assert sum(active) == Decimal("300.00")

    again = run_recognition(db, user_id)
    assert again.schedules_rebuilt == 0  # nothing new, nothing rebuilt


def test_second_delivery_keeps_what_is_already_booked(db: Session, user_id: int) -> None:
    contract(db, user_id, "K", "1,PRINT,1,300.00,,2025-01-01,2027-12-31,")
    accepted(upload(db, user_id, deliveries="D1,K,1,2025-03-31,0.25"))
    run_recognition(db, user_id)
    next_month(db)
    accepted(upload(db, user_id, deliveries="D2,K,1,2025-08-31,0.25"))
    run_recognition(db, user_id)
    active = [
        (s, posting, a) for s, status, posting, _, a in lines_of(db) if status != "SUPERSEDED"
    ]
    assert active == [
        ("202503", "202507", Decimal("75.00")),
        ("202508", "202508", Decimal("75.00")),
        ("202712", None, Decimal("150.00")),
    ]


def test_delivery_that_would_change_posted_revenue_is_reported_not_applied(
    db: Session, user_id: int
) -> None:
    """Posted lines never change (CLAUDE.md rule 3). The plan defines no reversal for this."""
    contract(db, user_id, "K", "1,PRINT,1,300.00,,2025-01-01,2025-06-30,")
    run_recognition(db, user_id)
    db.execute(update(ScheduleLine).values(status=ScheduleLineStatus.POSTED))
    next_month(db)
    accepted(upload(db, user_id, deliveries="D1,K,1,2025-03-31,0.25"))
    summary = run_recognition(db, user_id)
    assert [s.reason for s in summary.skipped] == ["DELIVERY_AFTER_BOOKING"]
    assert [(s, st, a) for s, st, _, _, a in lines_of(db)] == [
        ("202506", "POSTED", Decimal("300.00"))
    ]


# --------------------------------------------------------------------------- P3-T5 balances


def test_b01_shape_deferred_at_end_of_january(db: Session) -> None:
    """Plan §11.3: 12,600 billed, 2,333.33 recognised in January, 10,266.67 deferred."""
    seed.seed_accounts(db)
    seed.seed_periods(db, "202501")
    uid = make_user(db, [Role.ACCOUNTANT]).id
    accepted(
        upload(
            db,
            uid,
            customers="C1,Acme,GB",
            products="SUB,Sub,,12000.00,LIST_PRICE,,,RATABLE_MONTHLY,Y,4100,\n"
            "TRAIN,Training,,1500.00,LIST_PRICE,,,POINT_IN_TIME,Y,4300,",
            contracts="B01,C1,2025-01-01,2025-12-31,NEW,2025-01-01",
            contract_lines="B01,1,SUB,1,12000.00,900.00,2025-01-01,2025-12-31,\n"
            "B01,2,TRAIN,1,1500.00,,2025-01-15,2025-01-15,2025-01-15",
            invoices="INV-1,B01,2025-01-01,1,12600.00",
        )
    )
    run_recognition(db, uid)
    rows = contract_balances(db, contract_id(db, "B01"))
    assert balance_at(rows, "202501") == (1_026_667, 0)
    assert rows[0].recognised == 233_333


def test_revenue_without_an_invoice_is_unbilled_until_billed(db: Session, user_id: int) -> None:
    """J03 shape: catch-up 7 x 100.00 with nothing billed, then an invoice clears it."""
    contract(db, user_id, "K", "1,SUB,1,1200.00,,2025-01-01,2025-12-31,")
    run_recognition(db, user_id)
    cid = contract_id(db, "K")
    assert balance_at(contract_balances(db, cid), "202507") == (0, 70_000)

    next_month(db)
    accepted(upload(db, user_id, invoices="INV-1,K,2025-08-05,1,1200.00"))
    run_recognition(db, user_id)
    assert balance_at(contract_balances(db, cid), "202508") == (40_000, 0)  # 1,200 - 800 earned


def test_invoice_dated_in_a_closed_period_posts_to_the_period_it_arrived_in(
    db: Session, user_id: int
) -> None:
    """D6."""
    contract(db, user_id, "K", "1,SUB,1,1200.00,,2025-01-01,2025-12-31,")
    next_month(db)
    accepted(upload(db, user_id, invoices="INV-1,K,2025-07-20,1,1200.00"))
    rows = contract_balances(db, contract_id(db, "K"))
    assert [(r.period, r.billings) for r in rows] == [("202508", 120_000)]


def test_credit_note_beyond_deferred_is_e009_at_upload(db: Session, user_id: int) -> None:
    """§5.6: reversing recognised revenue is out of scope. Deferred here is 500.00."""
    contract(db, user_id, "K", "1,SUB,1,1200.00,,2025-01-01,2025-12-31,")
    accepted(upload(db, user_id, invoices="INV-1,K,2025-07-01,1,1200.00"))
    run_recognition(db, user_id)  # 7 x 100.00 recognised

    (refused,) = upload(db, user_id, credit_notes="CN-1,INV-1,2025-07-31,500.01,Too much")
    assert refused.status == "REJECTED"
    error = db.scalar(
        select(ValidationError).where(ValidationError.upload_file_id == refused.upload_id)
    )
    assert error is not None and error.error_code == "E009"
    assert "deferred revenue" in error.message

    (allowed,) = upload(db, user_id, credit_notes="CN-2,INV-1,2025-07-31,500.00,Exactly deferred")
    assert allowed.status == "ACCEPTED"
    assert balance_at(contract_balances(db, contract_id(db, "K")), "202507") == (0, 0)


def test_credit_note_in_the_same_upload_as_its_invoice(db: Session, user_id: int) -> None:
    contract(db, user_id, "K", "1,SUB,1,1200.00,,2025-01-01,2025-12-31,")
    summaries = upload(
        db,
        user_id,
        invoices="INV-1,K,2025-07-01,1,1200.00",
        credit_notes="CN-1,INV-1,2025-07-02,100.00,Goodwill",
    )
    accepted(summaries)


# --------------------------------------------------------------------------- P3-T6 endpoints


def built(db: Session, user_id: int) -> int:
    contract(
        db,
        user_id,
        "000123-K",
        "1,SUB,1,1200.00,100.00,2025-01-01,2025-12-31,",
        "2,PRINT,1,300.00,,2025-01-01,2027-12-31,2027-12-31",
        "3,SETUP,1,500.00,,2025-01-01,2025-01-31,",
    )
    accepted(
        upload(
            db,
            user_id,
            invoices="INV-1,000123-K,2025-07-01,1,1900.00",
            credit_notes="CN-1,INV-1,2025-07-02,50.00,Goodwill",
            deliveries="DLV-1,000123-K,2,2025-03-31,0.25",
        )
    )
    run_recognition(db, user_id)
    return contract_id(db, "000123-K")


def test_contract_detail_lists_its_versions(api: TestClient, db: Session, user_id: int) -> None:
    cid = built(db, user_id)
    accepted(
        upload(db, user_id, contracts="000123-K,C1,2025-01-01,2027-12-31,CANCELLATION,2025-12-31")
    )
    body = api.get(f"/api/v1/contracts/{cid}").json()
    assert body["contract_code"] == "000123-K" and body["current_version_no"] == 2
    assert [(v["version_no"], v["event_type"]) for v in body["versions"]] == [
        (1, "NEW"),
        (2, "CANCELLATION"),
    ]
    assert body["versions"][0]["transaction_price"] == "1900.00"


def test_version_shows_lines_obligations_and_deliveries(
    api: TestClient, db: Session, user_id: int
) -> None:
    cid = built(db, user_id)
    body = api.get(f"/api/v1/contracts/{cid}/versions/1").json()
    assert body["event_type"] == "NEW" and body["transaction_price"] == "1900.00"
    assert [line["line_no"] for line in body["lines"]] == [1, 2, 3]
    first = body["lines"][0]
    assert (first["product_code"], first["discount"], first["net_price"]) == (
        "SUB", "100.00", "1100.00",
    )  # fmt: skip
    assert body["lines"][2]["is_separate_obligation"] is False

    # TP 1,900.00 by SSP 1,200 : 300: 1,520.00 and 380.00. The setup fee has no obligation.
    obligations = {o["line_no"]: o for o in body["obligations"]}
    assert set(obligations) == {1, 2}
    assert obligations[1]["allocated_amount"] == "1520.00"
    assert obligations[1]["ssp_amount"] == "1200.00"
    assert obligations[2]["allocated_amount"] == "380.00"
    assert obligations[2]["method"] == "POINT_IN_TIME"

    (delivery,) = body["deliveries"]
    assert (delivery["delivery_code"], delivery["line_no"]) == ("DLV-1", 2)
    assert delivery["units_fraction"] == "0.250000"

    assert api.get(f"/api/v1/contracts/{cid}/versions/9").status_code == 404
    assert api.get("/api/v1/contracts/999999/versions/1").status_code == 404


def test_billing_shows_documents_and_the_rollforward(
    api: TestClient, db: Session, user_id: int
) -> None:
    cid = built(db, user_id)
    body = api.get(f"/api/v1/contracts/{cid}/billing").json()
    assert [(i["invoice_number"], i["total_amount"]) for i in body["invoices"]] == [
        ("INV-1", "1900.00")
    ]
    (note,) = body["credit_notes"]
    assert (note["credit_note_number"], note["invoice_number"], note["amount"]) == (
        "CN-1", "INV-1", "50.00",
    )  # fmt: skip

    (row,) = body["balances"]
    # Recognised: line 1 is 1,520 / 12 = 126.67 x 7 = 886.69; line 2 is a 95.00 delivery.
    assert row["period"] == "202507"
    assert (row["billings"], row["credit_notes"]) == ("1900.00", "50.00")
    assert row["recognised"] == "981.69"
    assert row["closing_deferred"] == "868.31"
    assert (body["deferred"], body["unbilled"]) == ("868.31", "0.00")
    assert api.get("/api/v1/contracts/999999/billing").status_code == 404


def test_billing_of_a_contract_with_nothing_yet(api: TestClient, db: Session, user_id: int) -> None:
    contract(db, user_id, "K", "1,SUB,1,1200.00,,2025-01-01,2025-12-31,")
    body = api.get(f"/api/v1/contracts/{contract_id(db, 'K')}/billing").json()
    assert body == {
        "invoices": [],
        "credit_notes": [],
        "balances": [],
        "deferred": "0.00",
        "unbilled": "0.00",
    }


def test_source_rows_show_every_uploaded_row_of_the_contract(
    api: TestClient, db: Session, user_id: int
) -> None:
    """CLAUDE.md rule 5."""
    cid = built(db, user_id)
    contract(db, user_id, "OTHER", "1,SUB,1,1200.00,,2025-01-01,2025-12-31,")  # must stay out
    body = api.get(f"/api/v1/contracts/{cid}/source-rows").json()
    kinds = sorted(item["record_type"] for item in body["items"])
    assert kinds == [
        "contract", "contract_line", "contract_line", "contract_line",
        "credit_note", "delivery", "invoice", "invoice_line",
    ]  # fmt: skip
    assert body["total"] == 8
    assert {item["id"] for item in body["items"]} == set(range(1, 9))
    line = next(i for i in body["items"] if i["record_type"] == "contract_line")
    assert line["filename"] == "contract_lines.csv" and line["source_row"] == 2
    assert line["payload"]["contract_id"] == "000123-K"  # leading zeros, as in the file

    assert api.get(f"/api/v1/contracts/{cid}/source-rows?page_size=3").json()["total"] == 8
    assert api.get(f"/api/v1/contracts/{cid}/source-rows?sort=payload").status_code == 422
    csv_response = api.get(f"/api/v1/contracts/{cid}/source-rows?format=csv")
    assert csv_response.status_code == 200 and "contract_line" in csv_response.text
    assert api.get("/api/v1/contracts/999999/source-rows").status_code == 404
