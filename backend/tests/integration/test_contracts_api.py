"""P2-T4 acceptance: contract list, contract schedule, recognition-run job (plan §8, §10)."""

import csv
import importlib.util
import io
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

import app.jobs.worker  # noqa: F401  (registers what the real worker registers)
from app.auth.roles import Role
from app.config import get_settings
from app.ingestion.loader import load_upload
from app.ingestion.templates import TEMPLATES
from app.jobs.queue import HANDLERS, run_next_job
from app.models import (
    AccountingPeriod,
    AuditLog,
    Contract,
    RevenueSchedule,
    ScheduleLine,
    UploadFile,
)
from app.models.enums import JobType, PeriodStatus, UploadTemplate
from app.services.recognition_run import run_recognition
from tests.integration.conftest import make_user, sign_in

REPO = Path(__file__).resolve().parents[3]
Factory = sessionmaker[Session]

PRODUCTS = (
    "SUB,Pro subscription,,1200.00,LIST_PRICE,,,RATABLE_MONTHLY,Y,4100,\n"
    "DAILY,Daily service,,100.00,LIST_PRICE,,,RATABLE_DAILY,Y,4100,"
)


def _seed_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("seed", REPO / "tools" / "seed.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


seed = _seed_module()


def upload(db: Session, user_id: int, **files: str) -> None:
    batch = []
    for name, body in files.items():
        template = TEMPLATES[UploadTemplate(name)]
        record = UploadFile(
            template=template.name,
            original_filename=f"{name}.csv",
            sha256="0" * 64,
            stored_path="(test)",
            uploaded_by=user_id,
            period_key="202501",
        )
        db.add(record)
        batch.append((record, (",".join(template.headers) + "\n" + body.strip() + "\n").encode()))
    db.flush()
    summaries = load_upload(db, batch, user_id)
    assert all(s.status == "ACCEPTED" for s in summaries), summaries


def contract(
    db: Session, user_id: int, code: str, customer: str = "C1", amount: str = "1200.00"
) -> None:
    upload(
        db,
        user_id,
        contracts=f"{code},{customer},2025-01-01,2025-12-31,NEW,2025-01-01",
        contract_lines=f"{code},1,SUB,1,{amount},,2025-01-01,2025-12-31,",
    )


@pytest.fixture
def user_id(db: Session) -> int:
    seed.seed_accounts(db)
    seed.seed_periods(db, "202501")
    uid = make_user(db, [Role.ACCOUNTANT]).id
    upload(db, uid, products=PRODUCTS, customers="C1,Acme Ltd,GB\nC2,Northwind,US")
    return uid


@pytest.fixture
def api(client: TestClient, db: Session, user_id: int) -> TestClient:
    sign_in(client, make_user(db, [Role.UPLOADER]))
    return client


def contract_id(db: Session, code: str) -> int:
    found = db.scalar(select(Contract.id).where(Contract.contract_code == code))
    assert found is not None
    return found


def codes(api: TestClient, query: str = "") -> list[str]:
    body = api.get(f"/api/v1/contracts?{query}").json()
    return [item["contract_code"] for item in body["items"]]


# --------------------------------------------------------------------------- GET /contracts


def test_contract_list_shows_the_current_version(
    api: TestClient, db: Session, user_id: int
) -> None:
    contract(db, user_id, "000123-U01")
    body = api.get("/api/v1/contracts").json()
    assert body["total"] == 1
    (item,) = body["items"]
    assert item["contract_code"] == "000123-U01"  # leading zeros survive
    assert (item["customer_code"], item["customer_name"]) == ("C1", "Acme Ltd")
    assert item["transaction_price"] == "1200.00"  # D1: a string, never a float
    assert (item["status"], item["current_version_no"], item["event_type"]) == ("ACTIVE", 1, "NEW")
    assert (item["start_date"], item["end_date"]) == ("2025-01-01", "2025-12-31")
    assert item["booked_period"] == "202501" and item["has_schedule"] is False


def test_contract_list_pages_and_sorts_on_the_server(
    api: TestClient, db: Session, user_id: int
) -> None:
    for i in range(5):
        contract(db, user_id, f"K{i}", amount=f"{(5 - i) * 100}.00")
    page2 = api.get("/api/v1/contracts?page=2&page_size=2").json()
    assert page2["total"] == 5
    assert [c["contract_code"] for c in page2["items"]] == ["K2", "K3"]
    assert codes(api, "sort=-contract_code&page_size=1") == ["K4"]
    assert codes(api, "sort=transaction_price")[0] == "K4"  # 100.00 is the smallest
    assert api.get("/api/v1/contracts?page_size=101").status_code == 422
    bad = api.get("/api/v1/contracts?sort=password_hash")
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "INVALID_SORT"


def test_contract_list_filters(api: TestClient, db: Session, user_id: int) -> None:
    contract(db, user_id, "ALPHA", "C1")
    contract(db, user_id, "BETA", "C2")
    upload(
        db,
        user_id,
        contracts="GAMMA,C2,2025-01-01,2025-12-31,NEW,2025-01-01",
        contract_lines="GAMMA,1,DAILY,1,10.00,,2025-02-15,2025-12-31,",
    )
    assert codes(api, "customer=north") == ["BETA", "GAMMA"]  # customer name, any case
    assert codes(api, "customer=C1") == ["ALPHA"]  # customer code
    assert codes(api, "contract=ph") == ["ALPHA"]
    assert codes(api, "product=daily") == ["GAMMA"]
    assert codes(api, "period_from=202501&period_to=202501") == ["ALPHA", "BETA", "GAMMA"]
    assert codes(api, "period_from=202502") == []
    assert api.get("/api/v1/contracts?period_from=2025-01").status_code == 422


def test_contract_list_follows_events_and_finds_products_of_earlier_versions(
    api: TestClient, db: Session, user_id: int
) -> None:
    contract(db, user_id, "K")
    upload(db, user_id, contracts="K,C1,2025-01-01,2025-12-31,CANCELLATION,2025-06-30")
    (item,) = api.get("/api/v1/contracts").json()["items"]
    assert (item["status"], item["current_version_no"]) == ("CANCELLED", 2)
    assert item["event_type"] == "CANCELLATION" and item["effective_date"] == "2025-06-30"
    assert codes(api, "product=SUB") == ["K"]  # the line is on version 1


def test_contract_list_exports_every_row(api: TestClient, db: Session, user_id: int) -> None:
    contract(db, user_id, "000123-A")
    contract(db, user_id, "B")
    response = api.get("/api/v1/contracts?format=csv&page_size=1")
    assert response.status_code == 200 and response.headers["content-type"].startswith("text/csv")
    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert [r["contract_code"] for r in rows] == ["000123-A", "B"]
    assert rows[0]["transaction_price"] == "1200.00"


def test_one_contract_and_unknown_contract(api: TestClient, db: Session, user_id: int) -> None:
    contract(db, user_id, "000123-U01")
    cid = contract_id(db, "000123-U01")
    body = api.get(f"/api/v1/contracts/{cid}").json()
    assert body["contract_code"] == "000123-U01" and body["transaction_price"] == "1200.00"
    assert body["has_schedule"] is False
    run_recognition(db, user_id)
    assert api.get(f"/api/v1/contracts/{cid}").json()["has_schedule"] is True
    assert api.get("/api/v1/contracts/999999").status_code == 404


def test_periods_list_finds_the_current_period(api: TestClient) -> None:
    body = api.get("/api/v1/periods?page_size=2").json()
    assert body["total"] == 48
    assert [p["period_key"] for p in body["items"]] == ["202501", "202502"]
    (current,) = api.get("/api/v1/periods?status=OPEN").json()["items"]
    assert (current["period_key"], current["status"]) == ("202501", "OPEN")
    assert (current["start_date"], current["end_date"]) == ("2025-01-01", "2025-01-31")
    assert api.get("/api/v1/periods?status=NOPE").status_code == 422
    assert api.get("/api/v1/periods?sort=closed_by").status_code == 422


# --------------------------------------------------------------------------- GET .../schedule


def test_schedule_lists_the_lines_and_totals_every_page(
    api: TestClient, db: Session, user_id: int
) -> None:
    contract(db, user_id, "U01")
    run_recognition(db, user_id)
    body = api.get(f"/api/v1/contracts/{contract_id(db, 'U01')}/schedule?page_size=5").json()
    assert body["total"] == 12 and len(body["items"]) == 5
    assert body["total_amount"] == "1200.00"  # all 12 lines, not just the 5 on this page
    first = body["items"][0]
    assert (first["service_period"], first["amount"], first["status"]) == (
        "202501", "100.00", "PENDING",
    )  # fmt: skip
    assert (first["version_no"], first["line_no"], first["product_code"]) == (1, 1, "SUB")
    assert first["method"] == "RATABLE_MONTHLY"
    assert first["posting_period"] == "202501" and first["is_catch_up"] is False  # §5.4
    assert body["items"][1]["posting_period"] is None  # February is still in the future


def test_b01_schedule_through_the_api(api: TestClient, db: Session, user_id: int) -> None:
    contract(db, user_id, "B01", amount="11200.00")
    run_recognition(db, user_id)
    body = api.get(f"/api/v1/contracts/{contract_id(db, 'B01')}/schedule").json()
    assert [line["amount"] for line in body["items"]] == ["933.33"] * 11 + ["933.37"]
    assert body["total_amount"] == "11200.00"


def test_schedule_sorts_and_filters_by_service_period(
    api: TestClient, db: Session, user_id: int
) -> None:
    contract(db, user_id, "K")
    run_recognition(db, user_id)
    url = f"/api/v1/contracts/{contract_id(db, 'K')}/schedule"
    assert api.get(f"{url}?sort=-service_period").json()["items"][0]["service_period"] == "202512"
    q1 = api.get(f"{url}?period_from=202501&period_to=202503").json()
    assert [line["service_period"] for line in q1["items"]] == ["202501", "202502", "202503"]
    assert q1["total"] == 3 and q1["total_amount"] == "300.00"  # the total follows the filter
    assert api.get(f"{url}?sort=schedule_id").status_code == 422


def test_schedule_csv_has_every_line(api: TestClient, db: Session, user_id: int) -> None:
    contract(db, user_id, "K")
    run_recognition(db, user_id)
    cid = contract_id(db, "K")
    response = api.get(f"/api/v1/contracts/{cid}/schedule?format=csv&page_size=1")
    assert f"contract_{cid}_schedule.csv" in response.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert len(rows) == 12 and rows[-1]["amount"] == "100.00"


def test_schedule_of_a_contract_without_one_and_of_no_contract(
    api: TestClient, db: Session, user_id: int
) -> None:
    contract(db, user_id, "K")
    body = api.get(f"/api/v1/contracts/{contract_id(db, 'K')}/schedule").json()
    assert (body["items"], body["total"], body["total_amount"]) == ([], 0, "0.00")
    missing = api.get("/api/v1/contracts/999999/schedule")
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "NOT_FOUND"


def test_superseded_lines_stay_visible_but_do_not_count(
    api: TestClient, db: Session, user_id: int
) -> None:
    contract(db, user_id, "K")
    run_recognition(db, user_id)
    db.execute(
        update(ScheduleLine)
        .where(ScheduleLine.service_period >= "202507")
        .values(status="SUPERSEDED")
    )
    db.flush()
    body = api.get(f"/api/v1/contracts/{contract_id(db, 'K')}/schedule").json()
    assert body["total"] == 12 and body["total_amount"] == "600.00"


# --------------------------------------------------------------------------- recognition run


@pytest.fixture
def stack(
    committed: Factory,
    committed_client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> TestClient:
    """Real commits and a temp upload folder, signed in as an ACCOUNTANT."""
    monkeypatch.setattr(get_settings(), "upload_dir", str(tmp_path))
    with committed() as db:
        seed.seed_accounts(db)
        seed.seed_periods(db, "202501")
        user = make_user(db, [Role.ACCOUNTANT])
        db.commit()
        sign_in(committed_client, user)
    return committed_client


def _post_files(api: TestClient, **bodies: str) -> None:
    files = []
    for name, body in bodies.items():
        template = TEMPLATES[UploadTemplate(name)]
        content = ",".join(template.headers) + "\n" + body.strip() + "\n"
        files.append(("files", (f"{name}.csv", content.encode(), "text/csv")))
    assert api.post("/api/v1/uploads", files=files).status_code == 202


def _job(api: TestClient, job_id: int) -> dict[str, Any]:
    body: dict[str, Any] = api.get(f"/api/v1/jobs/{job_id}").json()
    return body


def test_the_real_worker_knows_recognition_jobs() -> None:
    assert JobType.INGEST in HANDLERS and JobType.RECOGNITION in HANDLERS


def test_upload_run_and_schedule_end_to_end(stack: TestClient, committed: Factory) -> None:
    """Upload -> worker -> POST recognition-run -> worker -> GET schedule."""
    _post_files(
        stack,
        customers="C1,Acme,GB",
        products=PRODUCTS,
        contracts="U01,C1,2025-01-01,2025-12-31,NEW,2025-01-01\n"
        "LATER,C1,2025-01-01,2025-12-31,NEW,2025-01-01",
        contract_lines="U01,1,SUB,1,1200.00,,2025-01-01,2025-12-31,\n"
        "LATER,1,DAILY,1,10.00,,2025-02-15,2025-12-31,",
    )
    assert run_next_job(committed) is True  # the upload

    response = stack.post("/api/v1/periods/202501/recognition-run")
    assert response.status_code == 202, response.text
    job_id = response.json()["job_id"]
    queued = _job(stack, job_id)
    assert (queued["job_type"], queued["status"]) == ("RECOGNITION", "QUEUED")

    assert run_next_job(committed) is True  # the run
    job = _job(stack, job_id)
    assert (job["status"], job["progress"], job["error"]) == ("DONE", 100, None)
    result = job["result"]
    assert result["period_key"] == "202501"
    assert (result["contracts_generated"], result["obligations_created"]) == (2, 2)
    assert result["schedule_lines_created"] == 12 + 11  # LATER is daily, Feb to Dec
    assert result["skipped"] == []
    assert (result["lines_booked"], result["catch_up_lines"]) == (1, 0)  # only January is due

    listed = {c["contract_code"]: c for c in stack.get("/api/v1/contracts").json()["items"]}
    assert listed["U01"]["has_schedule"] is True and listed["LATER"]["has_schedule"] is True
    schedule = stack.get(f"/api/v1/contracts/{listed['U01']['id']}/schedule").json()
    assert schedule["total"] == 12 and schedule["total_amount"] == "1200.00"

    with committed() as db:
        saved = db.scalar(select(RevenueSchedule))
        assert saved is not None and saved.generated_by_job_id == job_id
        actions = set(db.scalars(select(AuditLog.action)))
    assert {"RECOGNITION_RUN_REQUESTED", "RECOGNITION_RUN"} <= actions


def test_a_second_run_adds_nothing(stack: TestClient, committed: Factory) -> None:
    _post_files(
        stack,
        customers="C1,Acme,GB",
        products=PRODUCTS,
        contracts="U01,C1,2025-01-01,2025-12-31,NEW,2025-01-01",
        contract_lines="U01,1,SUB,1,1200.00,,2025-01-01,2025-12-31,",
    )
    run_next_job(committed)
    stack.post("/api/v1/periods/202501/recognition-run")
    run_next_job(committed)
    second = stack.post("/api/v1/periods/202501/recognition-run").json()["job_id"]
    run_next_job(committed)
    assert _job(stack, second)["result"]["schedule_lines_created"] == 0


@pytest.mark.parametrize(
    ("key", "status", "code"),
    [
        ("202412", 404, "NOT_FOUND"),
        ("202412x", 404, "NOT_FOUND"),
        ("202502", 409, "PERIOD_NOT_CURRENT"),  # FUTURE
    ],
)
def test_only_the_current_period_can_run(
    stack: TestClient, committed: Factory, key: str, status: int, code: str
) -> None:
    response = stack.post(f"/api/v1/periods/{key}/recognition-run")
    assert response.status_code == status
    assert response.json()["error"]["code"] == code


def test_closed_period_is_refused_and_closing_is_allowed(
    stack: TestClient, committed: Factory
) -> None:
    def set_status(status: PeriodStatus) -> None:
        with committed() as db:
            db.execute(
                update(AccountingPeriod)
                .where(AccountingPeriod.period_key == "202501")
                .values(status=status)
            )
            db.commit()

    set_status(PeriodStatus.CLOSING)
    assert stack.post("/api/v1/periods/202501/recognition-run").status_code == 202
    set_status(PeriodStatus.CLOSED)
    refused = stack.post("/api/v1/periods/202501/recognition-run")
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "PERIOD_NOT_CURRENT"
