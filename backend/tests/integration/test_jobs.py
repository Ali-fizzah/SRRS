"""P1-T9 acceptance: POST /uploads queues an INGEST job, the worker completes it, progress shows.

These tests commit for real: the queue depends on separate connections seeing each other's
work, which a rolled-back test transaction cannot show. `committed` wipes the tables after.
"""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, sessionmaker

import app.jobs.ingest  # noqa: F401  (registers the INGEST handler)
from app.auth.roles import Role
from app.config import get_settings
from app.ingestion.templates import TEMPLATES
from app.jobs.queue import FAILURE_HANDLERS, HANDLERS, claim_next, enqueue, run_next_job
from app.models import (
    AccountingPeriod,
    AuditLog,
    ContractLine,
    Customer,
    Delivery,
    Invoice,
    JobRun,
    UploadFile,
    ValidationError,
)
from app.models.enums import JobType, PeriodStatus, UploadTemplate
from tests.integration.conftest import make_user, sign_in

REPO = Path(__file__).resolve().parents[3]
Factory = sessionmaker[Session]
GOOD_CUSTOMERS = b"customer_id,name,country\nC1,Acme,GB\n"


def _seed_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("seed", REPO / "tools" / "seed.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def api(
    committed: Factory,
    committed_client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> TestClient:
    """Signed in as an UPLOADER; accounts and periods seeded; files stored in a temp folder."""
    monkeypatch.setattr(get_settings(), "upload_dir", str(tmp_path))
    seed = _seed_module()
    with committed() as db:
        seed.seed_accounts(db)
        seed.seed_periods(db, "202501")
        user = make_user(db, [Role.UPLOADER])
        db.commit()
        sign_in(committed_client, user)
    return committed_client


def post(api: TestClient, *files: tuple[str, bytes]) -> Any:
    return api.post(
        "/api/v1/uploads", files=[("files", (name, body, "text/csv")) for name, body in files]
    )


def job_of(api: TestClient, job_id: int) -> dict[str, Any]:
    response = api.get(f"/api/v1/jobs/{job_id}")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def count(factory: Factory, model: type) -> int:
    with factory() as db:
        return db.scalar(select(func.count()).select_from(model)) or 0


# --------------------------------------------------------------------------- POST /uploads


def test_post_stores_the_file_and_queues_a_job(
    api: TestClient, committed: Factory, tmp_path: Path
) -> None:
    response = post(api, ("anything.csv", GOOD_CUSTOMERS))
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["files"][0]["template"] == "customers"  # recognised from the header row
    assert body["files"][0]["status"] == "RECEIVED"

    job = job_of(api, body["job_id"])
    assert (job["job_type"], job["status"], job["progress"]) == ("INGEST", "QUEUED", 0)
    assert count(committed, Customer) == 0  # nothing is loaded until the worker runs

    with committed() as db:
        record = db.get_one(UploadFile, body["files"][0]["upload_id"])
        stored = Path(record.stored_path)
        assert stored.parent == tmp_path and stored.read_bytes() == GOOD_CUSTOMERS
        assert stored.name != "anything.csv"
        assert len(record.sha256) == 64 and record.period_key == "202501"
        assert db.scalar(select(AuditLog).where(AuditLog.action == "UPLOAD_RECEIVED")) is not None


def test_path_tricks_in_the_filename_stay_harmless(
    api: TestClient, committed: Factory, tmp_path: Path
) -> None:
    body = post(api, ("../../evil.csv", GOOD_CUSTOMERS)).json()
    assert body["files"][0]["filename"] == "evil.csv"
    with committed() as db:
        stored = Path(db.get_one(UploadFile, body["files"][0]["upload_id"]).stored_path)
    assert stored.parent == tmp_path


def test_unknown_template_refuses_the_whole_request(api: TestClient, committed: Factory) -> None:
    response = post(api, ("customers.csv", GOOD_CUSTOMERS), ("notes.txt", b"hello"))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "UNKNOWN_TEMPLATE"
    assert count(committed, UploadFile) == 0 and count(committed, JobRun) == 0


def test_file_over_the_size_limit_is_refused(
    api: TestClient, committed: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "max_upload_bytes", 10)
    response = post(api, ("customers.csv", GOOD_CUSTOMERS))
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "FILE_TOO_LARGE"
    assert count(committed, UploadFile) == 0


def test_uploads_are_refused_while_no_period_is_open(api: TestClient, committed: Factory) -> None:
    with committed() as db:
        db.execute(
            update(AccountingPeriod)
            .where(AccountingPeriod.status == PeriodStatus.OPEN)
            .values(status=PeriodStatus.CLOSING)
        )
        db.commit()
    response = post(api, ("customers.csv", GOOD_CUSTOMERS))
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "NO_OPEN_PERIOD"
    assert count(committed, UploadFile) == 0


def test_unknown_job_is_404(api: TestClient) -> None:
    assert api.get("/api/v1/jobs/999").status_code == 404


# --------------------------------------------------------------------------- the worker


def test_worker_completes_a_mixed_upload(api: TestClient, committed: Factory) -> None:
    body = post(api, ("c.csv", b"customer_id,name,country\nC1,Acme,GB\nC2,Beta,GBR\n")).json()
    assert run_next_job(committed) is True
    job = job_of(api, body["job_id"])
    assert (job["status"], job["progress"], job["error"]) == ("DONE", 100, None)
    assert job["started_at"] and job["finished_at"]
    assert job["result"]["uploads"] == [
        {
            "upload_id": body["files"][0]["upload_id"],
            "template": "customers",
            "status": "PARTIAL",
            "total_rows": 2,
            "accepted_rows": 1,
            "rejected_rows": 1,
        }
    ]
    assert count(committed, Customer) == 1
    assert count(committed, ValidationError) == 1
    assert run_next_job(committed) is False  # the queue is now empty


def test_broken_headers_with_a_recognisable_name_get_e011(
    api: TestClient, committed: Factory
) -> None:
    body = post(api, ("customers_march.csv", b"customer,name\nC1,Acme\n")).json()
    assert body["files"][0]["template"] == "customers"  # from the filename
    run_next_job(committed)
    assert job_of(api, body["job_id"])["result"]["uploads"][0]["status"] == "REJECTED"
    with committed() as db:
        assert db.scalar(select(ValidationError.error_code)) == "E011"


def test_two_workers_never_claim_the_same_job(api: TestClient, committed: Factory) -> None:
    first = post(api, ("a.csv", GOOD_CUSTOMERS)).json()["job_id"]
    second = post(api, ("b.csv", GOOD_CUSTOMERS)).json()["job_id"]
    with committed() as worker_a, committed() as worker_b, committed() as worker_c:
        job_a = claim_next(worker_a)  # still uncommitted: the row is locked
        job_b = claim_next(worker_b)
        assert job_a is not None and job_b is not None
        assert (job_a.id, job_b.id) == (first, second)  # oldest first, the locked one skipped
        assert claim_next(worker_c) is None
        worker_a.rollback()
        worker_b.rollback()


def test_progress_is_visible_while_the_job_runs(
    api: TestClient, committed: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}

    def handler(db: Session, job: JobRun, report: Any) -> dict[str, Any]:
        report(50)
        seen.update(job_of(api, job.id))  # a separate connection, as the browser would be
        return {"ok": True}

    monkeypatch.setitem(HANDLERS, JobType.EXPORT, handler)
    with committed() as db:
        job_id = enqueue(db, JobType.EXPORT, {}, None).id
        db.commit()
    run_next_job(committed)
    assert (seen["status"], seen["progress"]) == ("RUNNING", 50)
    final = job_of(api, job_id)
    assert (final["status"], final["progress"], final["result"]) == ("DONE", 100, {"ok": True})


def test_ingest_reports_each_stage(
    api: TestClient, committed: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    stages: list[int] = []
    run_ingest = HANDLERS[JobType.INGEST]

    def spy(db: Session, job: JobRun, report: Any) -> dict[str, Any]:
        return run_ingest(db, job, lambda p: (stages.append(p), report(p))[1])

    monkeypatch.setitem(HANDLERS, JobType.INGEST, spy)
    post(api, ("c.csv", GOOD_CUSTOMERS))
    run_next_job(committed)
    assert stages == [10, 30, 60, 90]


def test_failed_job_finishes_its_files_so_they_cannot_block_the_close(
    api: TestClient, committed: Factory
) -> None:
    body = post(api, ("c.csv", GOOD_CUSTOMERS)).json()
    upload_id = body["files"][0]["upload_id"]
    with committed() as db:
        Path(db.get_one(UploadFile, upload_id).stored_path).unlink()  # the stored file vanished

    assert run_next_job(committed) is True
    job = job_of(api, body["job_id"])
    assert job["status"] == "FAILED" and "FileNotFoundError" in job["error"]
    with committed() as db:
        assert db.get_one(UploadFile, upload_id).status == "REJECTED"
        error = db.scalar(select(ValidationError))
        assert error is not None and error.error_code == "E009"
        assert db.scalar(select(AuditLog).where(AuditLog.action == "UPLOAD_FAILED")) is not None


def test_a_failing_job_leaves_none_of_its_work_behind(
    committed: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    def handler(db: Session, job: JobRun, report: Any) -> dict[str, Any]:
        db.add(Customer(customer_code="HALF", name="Half written", country="GB"))
        db.flush()
        raise RuntimeError("boom")

    monkeypatch.setitem(HANDLERS, JobType.EXPORT, handler)
    monkeypatch.delitem(FAILURE_HANDLERS, JobType.EXPORT, raising=False)
    with committed() as db:
        job_id = enqueue(db, JobType.EXPORT, {}, None).id
        db.commit()
    run_next_job(committed)
    with committed() as db:
        job = db.get_one(JobRun, job_id)
        assert (job.status, job.error) == ("FAILED", "RuntimeError: boom")
    assert count(committed, Customer) == 0


# --------------------------------------------------------------------------- the X02 workbook


def test_x02_inputs_complete_through_the_api_and_the_worker(
    api: TestClient, committed: Factory
) -> None:
    case = REPO / "benchmarks" / "cases" / "X02_revrec_mock_data" / "inputs"
    order = list(TEMPLATES)
    job_ids = []
    for month in sorted(p for p in case.iterdir() if p.is_dir()):
        files = sorted(month.glob("*.csv"), key=lambda p: order.index(UploadTemplate(p.stem)))
        response = post(api, *((p.name, p.read_bytes()) for p in files))
        assert response.status_code == 202, response.text
        job_ids.append(response.json()["job_id"])
    assert len(job_ids) == 20

    while run_next_job(committed):  # oldest first, so each month finds the months before it
        pass

    for job_id in job_ids:
        job = job_of(api, job_id)
        assert (job["status"], job["progress"]) == ("DONE", 100), job
        assert {u["status"] for u in job["result"]["uploads"]} == {"ACCEPTED"}, job["result"]
    assert count(committed, ContractLine) == 60
    assert count(committed, Delivery) == 22
    assert count(committed, Invoice) == 20
