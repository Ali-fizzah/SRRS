"""P1-T10: upload history, validation log, CSV export and original file (plan §7.1, §8)."""

import csv
import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.auth.roles import Role
from app.models import UploadFile, ValidationError
from app.models.enums import UploadStatus, UploadTemplate
from tests.integration.conftest import make_user, sign_in


@pytest.fixture
def api(client: TestClient, db: Session) -> TestClient:
    sign_in(client, make_user(db, [Role.UPLOADER]))
    return client


def add_upload(db: Session, name: str = "c.csv", period: str = "202601", **fields: object) -> int:
    uploader = make_user(db, [Role.ACCOUNTANT], email=f"{name}-{period}@test.local")
    upload = UploadFile(
        template=UploadTemplate.CUSTOMERS,
        original_filename=name,
        sha256="0" * 64,
        stored_path="/nowhere",
        uploaded_by=uploader.id,
        period_key=period,
        **fields,
    )
    db.add(upload)
    db.flush()
    return upload.id


def add_error(
    db: Session, upload_id: int, row: int, code: str = "E002", raw: str | None = "x"
) -> None:
    db.add(
        ValidationError(
            upload_file_id=upload_id,
            row_number=row,
            column_name="country",
            error_code=code,
            message=f"problem on row {row}",
            raw_value=raw,
        )
    )
    db.flush()


# --------------------------------------------------------------------------- history


def test_history_is_newest_first_with_the_uploader_name(api: TestClient, db: Session) -> None:
    first = add_upload(db, "a.csv")
    second = add_upload(
        db, "b.csv", status=UploadStatus.PARTIAL, total_rows=5, accepted_rows=3, rejected_rows=2
    )
    body = api.get("/api/v1/uploads").json()
    assert [i["id"] for i in body["items"]] == [second, first]
    assert body["total"] == 2 and (body["page"], body["page_size"]) == (1, 50)
    item = body["items"][0]
    assert item["status"] == "PARTIAL" and item["uploaded_by"] == "Test User"
    assert (item["total_rows"], item["accepted_rows"], item["rejected_rows"]) == (5, 3, 2)


def test_history_pages_on_the_server(api: TestClient, db: Session) -> None:
    ids = [add_upload(db, f"f{i}.csv") for i in range(5)]
    body = api.get("/api/v1/uploads?page=2&page_size=2").json()
    assert body["total"] == 5
    assert [i["id"] for i in body["items"]] == [ids[2], ids[1]]
    assert api.get("/api/v1/uploads?page_size=101").status_code == 422  # §8: at most 100


def test_history_sorts_on_the_server_by_allowed_columns_only(api: TestClient, db: Session) -> None:
    add_upload(db, "b.csv")
    add_upload(db, "a.csv")
    add_upload(db, "c.csv")
    names = lambda url: [i["original_filename"] for i in api.get(url).json()["items"]]  # noqa: E731
    assert names("/api/v1/uploads?sort=original_filename") == ["a.csv", "b.csv", "c.csv"]
    assert names("/api/v1/uploads?sort=-original_filename") == ["c.csv", "b.csv", "a.csv"]
    response = api.get("/api/v1/uploads?sort=stored_path;drop table users")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_SORT"


def test_history_filters_by_period(api: TestClient, db: Session) -> None:
    add_upload(db, "jan.csv", "202601")
    add_upload(db, "feb.csv", "202602")
    add_upload(db, "mar.csv", "202603")
    body = api.get("/api/v1/uploads?period_from=202602&period_to=202602").json()
    assert [i["original_filename"] for i in body["items"]] == ["feb.csv"]


def test_history_exports_every_row_as_csv(api: TestClient, db: Session) -> None:
    for i in range(3):
        add_upload(db, f"f{i}.csv")
    response = api.get("/api/v1/uploads?format=csv&page_size=1")  # paging does not limit the export
    assert response.status_code == 200
    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert len(rows) == 3 and rows[0]["original_filename"] == "f2.csv"
    assert rows[0]["uploaded_by"] == "Test User"


def test_one_upload_and_unknown_upload(api: TestClient, db: Session) -> None:
    upload_id = add_upload(db, "one.csv")
    assert api.get(f"/api/v1/uploads/{upload_id}").json()["original_filename"] == "one.csv"
    missing = api.get("/api/v1/uploads/999999")
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "NOT_FOUND"


# --------------------------------------------------------------------------- validation log


def test_errors_are_paged_in_file_order(api: TestClient, db: Session) -> None:
    upload_id = add_upload(db)
    for row in (9, 3, 5):
        add_error(db, upload_id, row)
    add_error(db, add_upload(db, "other.csv"), 2)  # another upload's error stays out
    body = api.get(f"/api/v1/uploads/{upload_id}/errors?page_size=2").json()
    assert body["total"] == 3
    assert [e["row_number"] for e in body["items"]] == [3, 5]
    assert body["items"][0]["message"] == "problem on row 3"
    assert api.get("/api/v1/uploads/999999/errors").status_code == 404


def test_errors_download_as_csv_with_every_field(api: TestClient, db: Session) -> None:
    """§7.1: upload id, row number, column, code, message and raw value."""
    upload_id = add_upload(db)
    add_error(db, upload_id, 4, "E002", "GBR")
    response = api.get(f"/api/v1/uploads/{upload_id}/errors?format=csv")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert f"upload_{upload_id}_errors.csv" in response.headers["content-disposition"]
    assert list(csv.DictReader(io.StringIO(response.text))) == [
        {
            "upload_id": str(upload_id),
            "row_number": "4",
            "column_name": "country",
            "error_code": "E002",
            "message": "problem on row 4",
            "raw_value": "GBR",
        }
    ]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('=HYPERLINK("http://evil","click")', '\'=HYPERLINK("http://evil","click")'),
        ("@SUM(A1)", "'@SUM(A1)"),
        ("+1+1", "'+1+1"),
        ("-1+1", "'-1+1"),
        ("-5.00", "-5.00"),  # a plain number stays a number
        ("000123", "000123"),
    ],
)
def test_csv_export_cannot_run_formulas_from_uploaded_text(
    api: TestClient, db: Session, raw: str, expected: str
) -> None:
    upload_id = add_upload(db)
    add_error(db, upload_id, 2, raw=raw)
    text = api.get(f"/api/v1/uploads/{upload_id}/errors?format=csv").text
    assert next(csv.DictReader(io.StringIO(text)))["raw_value"] == expected


# --------------------------------------------------------------------------- original file


def test_original_file_downloads_with_its_own_name(
    api: TestClient, db: Session, tmp_path: Path
) -> None:
    stored = tmp_path / "generated-name.csv"
    stored.write_bytes(b"customer_id,name,country\nC1,Caf\xc3\xa9,FR\n")
    upload_id = add_upload(db, "my customers.csv")
    record = db.get_one(UploadFile, upload_id)
    record.stored_path = str(stored)
    db.flush()
    response = api.get(f"/api/v1/uploads/{upload_id}/file")
    assert response.status_code == 200
    assert response.content == stored.read_bytes()
    assert "my%20customers.csv" in response.headers["content-disposition"] or (
        "my customers.csv" in response.headers["content-disposition"]
    )


def test_missing_stored_file_is_a_clear_404(api: TestClient, db: Session) -> None:
    response = api.get(f"/api/v1/uploads/{add_upload(db)}/file")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "FILE_MISSING"
