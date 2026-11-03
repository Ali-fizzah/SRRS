"""P1-T3 acceptance: every §8 endpoint lets in exactly the roles the plan gives it.

The matrix below is copied from plan §8, independently of the router code, so a
route that drifts from the plan (or a new route nobody listed) fails here.
"""

import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.auth.roles import RANK, Role
from app.main import app
from tests.integration.conftest import make_user, sign_in

PUBLIC = "PUBLIC"  # no sign-in needed
ANY = "ANY"  # any signed-in user

U, A, P, AD = Role.UPLOADER, Role.ACCOUNTANT, Role.APPROVER, Role.ADMIN

MATRIX: dict[tuple[str, str], str | Role] = {
    ("GET", "/health"): PUBLIC,
    # Auth
    ("POST", "/auth/login"): PUBLIC,
    ("POST", "/auth/logout"): PUBLIC,
    ("GET", "/auth/me"): ANY,
    # Users: ADMIN
    ("GET", "/users"): AD,
    ("POST", "/users"): AD,
    ("PATCH", "/users/{user_id}"): AD,
    # Templates: UPLOADER
    ("GET", "/templates"): U,
    ("GET", "/templates/{name}"): U,
    # Uploads: UPLOADER
    ("POST", "/uploads"): U,
    ("GET", "/uploads"): U,
    ("GET", "/uploads/{upload_id}"): U,
    ("GET", "/uploads/{upload_id}/errors"): U,
    ("GET", "/uploads/{upload_id}/file"): U,
    # Master data: read UPLOADER, write ACCOUNTANT
    ("GET", "/customers"): U,
    ("GET", "/products"): U,
    ("POST", "/products"): A,
    ("PATCH", "/products/{product_id}"): A,
    ("GET", "/products/{product_id}/ssp-history"): U,
    ("GET", "/gl-accounts"): U,
    ("POST", "/gl-accounts"): A,
    ("PATCH", "/gl-accounts/{account_id}"): A,
    ("GET", "/gl-mappings"): U,
    ("POST", "/gl-mappings"): A,
    ("PATCH", "/gl-mappings/{mapping_id}"): A,
    # Contracts: UPLOADER
    ("GET", "/contracts"): U,
    ("GET", "/contracts/{contract_id}"): U,
    ("GET", "/contracts/{contract_id}/versions/{version_no}"): U,
    ("GET", "/contracts/{contract_id}/schedule"): U,
    ("GET", "/contracts/{contract_id}/billing"): U,
    ("GET", "/contracts/{contract_id}/journal-lines"): U,
    ("GET", "/contracts/{contract_id}/source-rows"): U,
    # Engine: ACCOUNTANT
    ("POST", "/periods/{key}/recognition-run"): A,
    ("POST", "/periods/{key}/journals/generate"): A,
    # Jobs: any
    ("GET", "/jobs/{job_id}"): ANY,
    # Journals: view ACCOUNTANT, approve/post APPROVER (reverse: see journals.py)
    ("GET", "/journal-batches"): A,
    ("GET", "/journal-batches/{batch_id}"): A,
    ("POST", "/journal-batches/{batch_id}/approve"): P,
    ("POST", "/journal-batches/{batch_id}/send-back"): P,
    ("POST", "/journal-batches/{batch_id}/post"): P,
    ("POST", "/journal-entries/{entry_id}/reverse"): A,
    # Periods (reading: any signed-in user, see periods.py)
    ("GET", "/periods"): ANY,
    ("GET", "/periods/{key}/checklist"): ANY,
    ("POST", "/periods/{key}/start-close"): A,
    ("POST", "/periods/{key}/close"): P,
    ("POST", "/periods/{key}/reopen"): AD,
    # Reports: validation log UPLOADER, others ACCOUNTANT
    ("GET", "/reports/revenue-schedule"): A,
    ("GET", "/reports/deferred-rollforward"): A,
    ("GET", "/reports/recognized-vs-deferred"): A,
    ("GET", "/reports/journal-register"): A,
    ("GET", "/reports/gl-summary"): A,
    ("GET", "/reports/mrr-arr"): A,
    ("GET", "/reports/close-status"): A,
    ("GET", "/reports/validation-log"): U,
}

CALLERS: list[Role | None] = [None, U, A, P, AD]  # None = not signed in


def _app_routes() -> set[tuple[str, str]]:
    routes = set()
    # The OpenAPI document lists every endpoint the app serves (it is what /docs shows).
    for path, operations in app.openapi()["paths"].items():
        for method in operations:
            routes.add((method.upper(), path.removeprefix("/api/v1")))
    return routes


def _concrete(path: str) -> str:
    return re.sub(r"\{(\w+)\}", lambda m: "202601" if m.group(1) == "key" else "1", path)


def test_every_route_is_in_the_matrix() -> None:
    """CLAUDE.md: every route declares its minimum role. New routes must be added above."""
    assert _app_routes() == set(MATRIX)


@pytest.mark.parametrize("caller", CALLERS, ids=lambda c: c.value if c else "anonymous")
@pytest.mark.parametrize(
    ("method", "path"), sorted(MATRIX), ids=[f"{m} {p}" for m, p in sorted(MATRIX)]
)
def test_role_matrix(
    client: TestClient, db: Session, method: str, path: str, caller: Role | None
) -> None:
    required = MATRIX[(method, path)]
    if caller is not None:
        sign_in(client, make_user(db, [caller]))
    response = client.request(method, f"/api/v1{_concrete(path)}")

    if required == PUBLIC:
        allowed = True
    elif caller is None:
        allowed = False
        assert response.status_code == 401, response.text
    elif required == ANY:
        allowed = True
    else:
        assert isinstance(required, Role)
        allowed = RANK[caller] >= RANK[required]
        if not allowed:
            assert response.status_code == 403, response.text

    if allowed:
        assert response.status_code not in (401, 403), response.text
    else:
        assert response.json()["error"]["code"] in ("UNAUTHENTICATED", "FORBIDDEN")
