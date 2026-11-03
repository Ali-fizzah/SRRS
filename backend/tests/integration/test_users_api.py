"""P1-T3: user administration, with an audit_log row for every change (CLAUDE.md rule 8)."""

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.roles import Role
from app.models import AuditLog, User
from tests.integration.conftest import make_user, sign_in


def _as_admin(client: TestClient, db: Session) -> None:
    sign_in(client, make_user(db, [Role.ADMIN], email="boss@test.local"))


def _audit(db: Session, action: str) -> list[AuditLog]:
    return list(db.scalars(select(AuditLog).where(AuditLog.action == action)))


def test_create_user_writes_audit_without_password(client: TestClient, db: Session) -> None:
    _as_admin(client, db)
    response = client.post(
        "/api/v1/users",
        json={
            "email": "New.Person@Test.local",
            "full_name": "New Person",
            "password": "long-enough-1",
            "roles": ["UPLOADER", "ACCOUNTANT"],
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["email"] == "new.person@test.local"
    assert body["roles"] == ["ACCOUNTANT", "UPLOADER"]

    stored = db.scalar(select(User).where(User.email == "new.person@test.local"))
    assert stored is not None and stored.password_hash.startswith("$2")  # bcrypt, not plain

    (row,) = _audit(db, "USER_CREATED")
    assert row.entity_id == str(body["id"])
    assert row.after is not None and "password_hash" not in row.after
    assert "password" not in row.after


def test_duplicate_email_is_refused(client: TestClient, db: Session) -> None:
    make_user(db, [Role.UPLOADER], email="taken@test.local")
    _as_admin(client, db)
    response = client.post(
        "/api/v1/users",
        json={
            "email": "taken@test.local",
            "full_name": "Again",
            "password": "long-enough-1",
            "roles": ["UPLOADER"],
        },
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "EMAIL_TAKEN"


def test_invalid_body_uses_the_standard_error_shape(client: TestClient, db: Session) -> None:
    _as_admin(client, db)
    response = client.post(
        "/api/v1/users",
        json={"email": "x@test.local", "full_name": "X", "password": "short", "roles": []},
    )
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert {tuple(d["loc"]) for d in error["details"]} >= {
        ("body", "password"),
        ("body", "roles"),
    }


def test_update_roles_and_deactivate_takes_effect_immediately(
    client: TestClient, db: Session
) -> None:
    worker = make_user(db, [Role.UPLOADER], email="worker@test.local")
    sign_in(client, worker)
    assert client.get("/api/v1/auth/me").status_code == 200

    _as_admin(client, db)
    response = client.patch(
        f"/api/v1/users/{worker.id}", json={"roles": ["APPROVER"], "is_active": False}
    )
    assert response.status_code == 200, response.text
    assert response.json()["roles"] == ["APPROVER"]

    (row,) = _audit(db, "USER_UPDATED")
    assert row.before is not None and row.before["roles"] == ["UPLOADER"]
    assert row.after is not None and row.after["is_active"] is False

    # The worker's existing session stops working at once, before its token expires.
    sign_in(client, worker)
    assert client.get("/api/v1/auth/me").status_code == 401


def test_admin_cannot_lock_themselves_out(client: TestClient, db: Session) -> None:
    admin = make_user(db, [Role.ADMIN], email="solo@test.local")
    sign_in(client, admin)
    for change in ({"is_active": False}, {"roles": ["APPROVER"]}):
        response = client.patch(f"/api/v1/users/{admin.id}", json=change)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "SELF_LOCKOUT"


def test_list_users_is_paginated(client: TestClient, db: Session) -> None:
    for i in range(3):
        make_user(db, [Role.UPLOADER], email=f"user{i}@test.local")
    _as_admin(client, db)
    response = client.get("/api/v1/users?page=1&page_size=2")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 4 and len(body["items"]) == 2
    # §8: page_size is at most 100
    assert client.get("/api/v1/users?page_size=101").status_code == 422
