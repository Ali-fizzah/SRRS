"""P1-T11: master data lists page, sort and filter on the server (plan §4, §8)."""

import csv
import importlib.util
import io
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import ModuleType

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.roles import Role
from app.models import Customer, GlAccount, GlMapping, Product, SspRule
from app.models.enums import AccountRole, RecognitionMethod, SspSource
from tests.integration.conftest import make_user, sign_in

REPO = Path(__file__).resolve().parents[3]


def _seed_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("seed", REPO / "tools" / "seed.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


seed = _seed_module()


@pytest.fixture
def api(client: TestClient, db: Session) -> TestClient:
    sign_in(client, make_user(db, [Role.UPLOADER]))
    return client


def add_customers(db: Session, count: int) -> None:
    db.add_all(
        Customer(customer_code=f"C{i:03d}", name=f"Customer {i}", country="GB")
        for i in range(count)
    )
    db.flush()


def add_product(db: Session, code: str = "SUB", account: str = "4100", **fields: object) -> Product:
    account_id = db.scalar(select(GlAccount.id).where(GlAccount.account_code == account))
    assert account_id is not None
    values: dict[str, object] = {
        "product_code": code,
        "name": f"Product {code}",
        "list_price": Decimal("12000.00"),
        "recognition_method": RecognitionMethod.RATABLE_MONTHLY,
        "is_separate_obligation": True,
        "revenue_account_id": account_id,
        **fields,
    }
    product = Product(**values)
    db.add(product)
    db.flush()
    return product


def add_rule(db: Session, product: Product, value: str, valid_from: date) -> None:
    db.add(
        SspRule(
            product_id=product.id,
            ssp_source=SspSource.FIXED,
            ssp_value=Decimal(value),
            valid_from=valid_from,
        )
    )
    db.flush()


# --------------------------------------------------------------------------- acceptance


def test_customers_paginate_on_the_server(api: TestClient, db: Session) -> None:
    add_customers(db, 60)
    first = api.get("/api/v1/customers?page=1&page_size=25").json()
    assert first["total"] == 60 and len(first["items"]) == 25
    assert first["items"][0]["customer_code"] == "C000"

    third = api.get("/api/v1/customers?page=3&page_size=25").json()
    assert (third["page"], third["page_size"]) == (3, 25)
    assert [c["customer_code"] for c in third["items"]] == [f"C{i:03d}" for i in range(50, 60)]

    assert api.get("/api/v1/customers?page_size=101").status_code == 422  # §8: at most 100


@pytest.mark.parametrize(
    ("path", "sort"),
    [
        ("customers", "name"),
        ("products", "list_price"),
        ("gl-accounts", "type"),
        ("gl-mappings", "account_role"),
    ],
)
def test_every_list_sorts_by_allowed_columns_only(api: TestClient, path: str, sort: str) -> None:
    assert api.get(f"/api/v1/{path}?sort={sort}").status_code == 200
    assert api.get(f"/api/v1/{path}?sort=-{sort}").status_code == 200
    bad = api.get(f"/api/v1/{path}?sort=password_hash")
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "INVALID_SORT"


# --------------------------------------------------------------------------- customers


def test_customers_sort_and_filter(api: TestClient, db: Session) -> None:
    db.add_all(
        [
            Customer(customer_code="B-1", name="Northwind", country="GB"),
            Customer(customer_code="A-1", name="Contoso 100%", country="US"),
            Customer(customer_code="C-1", name="100 Things", country="FR"),
        ]
    )
    db.flush()
    codes = lambda query: [  # noqa: E731
        c["customer_code"] for c in api.get(f"/api/v1/customers?{query}").json()["items"]
    ]
    assert codes("") == ["A-1", "B-1", "C-1"]
    assert codes("sort=-country") == ["A-1", "B-1", "C-1"]
    assert codes("sort=name") == ["C-1", "A-1", "B-1"]
    assert codes("customer=north") == ["B-1"]  # name, any case
    assert codes("customer=c-") == ["C-1"]  # code
    assert codes("customer=100%25") == ["A-1"]  # % is a literal character, not a wildcard


def test_customers_keep_their_source_and_export_as_csv(api: TestClient, db: Session) -> None:
    add_customers(db, 3)
    response = api.get("/api/v1/customers?format=csv&page_size=1")
    assert response.status_code == 200
    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert len(rows) == 3  # paging does not limit the export
    assert rows[0]["customer_code"] == "C000" and "source_upload_id" in rows[0]


# --------------------------------------------------------------------------- products


def test_products_show_money_as_strings_and_the_latest_ssp(api: TestClient, db: Session) -> None:
    seed.seed_accounts(db)
    product = add_product(db, category="Subscription")
    add_rule(db, product, "900.50", date(2025, 1, 1))
    add_rule(db, product, "1000.00", date(2026, 1, 1))
    add_rule(db, product, "800.00", date(2024, 1, 1))
    (item,) = api.get("/api/v1/products").json()["items"]
    assert item["list_price"] == "12000.00"  # D1: a string, never a float
    assert item["ssp_value"] == "1000.00"  # the rule with the latest valid_from
    assert item["ssp_source"] == "FIXED"
    assert item["revenue_account"] == "4100"
    assert item["recognition_method"] == "RATABLE_MONTHLY"
    assert item["is_separate_obligation"] is True


def test_product_without_ssp_rule_still_lists(api: TestClient, db: Session) -> None:
    seed.seed_accounts(db)
    add_product(db)
    (item,) = api.get("/api/v1/products").json()["items"]
    assert item["ssp_source"] is None and item["ssp_value"] is None


def test_products_filter(api: TestClient, db: Session) -> None:
    seed.seed_accounts(db)
    add_product(db, "SUB-PRO", name="Pro subscription")
    add_product(db, "PRINT-1", name="Printed guide", account="4200")
    codes = [p["product_code"] for p in api.get("/api/v1/products?product=guide").json()["items"]]
    assert codes == ["PRINT-1"]


def test_ssp_history_is_newest_first_for_one_product(api: TestClient, db: Session) -> None:
    seed.seed_accounts(db)
    product = add_product(db)
    other = add_product(db, "OTHER")
    add_rule(db, product, "900.00", date(2025, 1, 1))
    add_rule(db, product, "1000.00", date(2026, 1, 1))
    add_rule(db, other, "1.00", date(2027, 1, 1))
    body = api.get(f"/api/v1/products/{product.id}/ssp-history").json()
    assert body["total"] == 2
    assert [(r["valid_from"], r["ssp_value"]) for r in body["items"]] == [
        ("2026-01-01", "1000.00"),
        ("2025-01-01", "900.00"),
    ]
    assert api.get("/api/v1/products/999999/ssp-history").status_code == 404


# --------------------------------------------------------------------------- GL


def test_gl_accounts_list_the_seeded_chart(api: TestClient, db: Session) -> None:
    seed.seed_accounts(db)
    body = api.get("/api/v1/gl-accounts").json()
    assert body["total"] == 6
    assert [a["account_code"] for a in body["items"]] == [
        "1100", "1150", "2400", "4100", "4200", "4300",
    ]  # fmt: skip
    assert body["items"][2]["type"] == "LIABILITY" and body["items"][2]["is_active"] is True


def test_gl_mappings_show_each_scope(api: TestClient, db: Session) -> None:
    seed.seed_accounts(db)
    seed.seed_gl_mappings(db)
    product = add_product(db)
    account_id = db.scalar(select(GlAccount.id).where(GlAccount.account_code == "4200"))
    assert account_id is not None
    db.add_all(
        [
            GlMapping(
                account_role=AccountRole.REVENUE, product_id=product.id, account_id=account_id
            ),
            GlMapping(
                account_role=AccountRole.REVENUE, product_category="Print", account_id=account_id
            ),
        ]
    )
    db.flush()
    body = api.get("/api/v1/gl-mappings?sort=account_role").json()
    assert body["total"] == 5
    scopes = {
        (m["account_role"], m["product_code"], m["product_category"], m["account_code"])
        for m in body["items"]
    }
    assert scopes == {
        ("AR", None, None, "1100"),
        ("UNBILLED_AR", None, None, "1150"),
        ("DEFERRED_REVENUE", None, None, "2400"),
        ("REVENUE", "SUB", None, "4200"),
        ("REVENUE", None, "Print", "4200"),
    }
    filtered = api.get("/api/v1/gl-mappings?product=SUB").json()
    assert [m["product_code"] for m in filtered["items"]] == ["SUB"]


def test_editing_is_refused_honestly_until_it_is_scheduled(client: TestClient, db: Session) -> None:
    sign_in(client, make_user(db, [Role.ACCOUNTANT]))
    response = client.post("/api/v1/products", json={})
    assert response.status_code == 501
    assert "not yet scheduled" in response.json()["error"]["message"]
