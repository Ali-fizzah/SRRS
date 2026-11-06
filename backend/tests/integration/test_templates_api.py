"""P1-T5 acceptance: GET /templates/{name} returns a CSV with headers and an example row."""

import csv
import io

import openpyxl
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.auth.roles import Role
from tests.integration.conftest import make_user, sign_in

NAMES = [
    "customers", "products", "contracts", "contract_lines", "invoices", "credit_notes",
    "deliveries",
]  # fmt: skip


@pytest.fixture
def uploader(client: TestClient, db: Session) -> TestClient:
    sign_in(client, make_user(db, [Role.UPLOADER]))
    return client


@pytest.mark.parametrize("name", NAMES)
def test_download_csv(uploader: TestClient, name: str) -> None:
    response = uploader.get(f"/api/v1/templates/{name}")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert response.headers["content-disposition"] == f'attachment; filename="{name}_template.csv"'
    rows = list(csv.reader(io.StringIO(response.text)))
    assert len(rows) == 2  # headers + one example row
    assert len(rows[0]) == len(rows[1])


def test_download_xlsx(uploader: TestClient) -> None:
    response = uploader.get("/api/v1/templates/invoices?format=xlsx")
    assert response.status_code == 200
    assert response.headers["content-disposition"].endswith('invoices_template.xlsx"')
    ws = openpyxl.load_workbook(io.BytesIO(response.content)).active
    assert ws is not None
    assert [c.value for c in ws[1]] == [
        "invoice_number", "contract_id", "invoice_date", "line_no", "amount",
    ]  # fmt: skip


def test_list_templates(uploader: TestClient) -> None:
    body = uploader.get("/api/v1/templates").json()
    assert [t["name"] for t in body] == NAMES
    assert [t["order"] for t in body] == list(range(1, 8))
    products = body[1]
    method = next(c for c in products["columns"] if c["name"] == "recognition_method")
    assert method["type"] == "CHOICE"
    assert method["choices"] == ["RATABLE_DAILY", "RATABLE_MONTHLY", "POINT_IN_TIME"]


def test_unknown_template_is_404_in_standard_shape(uploader: TestClient) -> None:
    response = uploader.get("/api/v1/templates/payments")
    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "NOT_FOUND"
    assert error["details"]["templates"] == NAMES


def test_unknown_format_is_rejected(uploader: TestClient) -> None:
    assert uploader.get("/api/v1/templates/customers?format=pdf").status_code == 422
