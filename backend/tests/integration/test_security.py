"""P6-T5: password policy, login rate limit, and attacks the API must shrug off."""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.passwords import hash_password, password_problem
from app.auth.rate_limit import LoginLimiter
from app.auth.roles import Role
from app.models import AuditLog, User
from app.schemas.auth import UserCreate
from tests.integration.conftest import make_user, sign_in

LOGIN = "/api/v1/auth/login"


@pytest.mark.parametrize(
    ("password", "problem"),
    [
        ("Short-Pass1", "12 characters"),
        ("alllowercase-1", "capital"),
        ("ALLUPPERCASE-1", "small"),
        ("No-Digits-At-All", "digit"),
        ("Good-Password1", None),
        ("ChangeMe-Admin1", None),  # the seeded admin's default must pass its own policy
    ],
)
def test_password_policy(password: str, problem: str | None) -> None:
    found = password_problem(password)
    if problem is None:
        assert found is None
    else:
        assert found is not None and problem in found


def test_the_api_refuses_a_weak_password(client: TestClient, db: Session) -> None:
    sign_in(client, make_user(db, [Role.ADMIN]))
    weak = client.post(
        "/api/v1/users",
        json={
            "email": "weak@test.local",
            "full_name": "Weak",
            "password": "weakpassword",
            "roles": ["UPLOADER"],
        },
    )
    assert weak.status_code == 422
    created = client.post(
        "/api/v1/users",
        json={
            "email": "strong@test.local",
            "full_name": "Strong",
            "password": "Strong-Password1",
            "roles": ["UPLOADER"],
        },
    ).json()
    changed = client.patch(f"/api/v1/users/{created['id']}", json={"password": "weakpassword"})
    assert changed.status_code == 422


def test_a_password_too_long_for_bcrypt_is_refused_not_cut_short() -> None:
    with pytest.raises(ValidationError):
        UserCreate(
            email="x@test.local",
            full_name="X",
            password="Aa1" + "x" * 80,
            roles=[Role.UPLOADER],
        )


def _user(db: Session, email: str = "guess@test.local") -> User:
    user = User(email=email, full_name="Guess", password_hash=hash_password("Right-Password1"))
    db.add(user)
    db.flush()
    return user


def _attempt(client: TestClient, password: str, email: str = "guess@test.local") -> int:
    return client.post(LOGIN, json={"email": email, "password": password}).status_code


def test_five_wrong_passwords_lock_the_email(client: TestClient, db: Session) -> None:
    _user(db)
    assert [_attempt(client, "wrong") for _ in range(5)] == [401] * 5
    locked = client.post(LOGIN, json={"email": "guess@test.local", "password": "wrong"})
    assert locked.status_code == 429
    assert locked.json()["error"]["code"] == "TOO_MANY_ATTEMPTS"
    assert int(locked.headers["Retry-After"]) > 0
    # Even the right password waits: otherwise a guess could still be confirmed.
    assert _attempt(client, "Right-Password1") == 429


def test_locking_is_audited_and_does_not_touch_other_emails(
    client: TestClient, db: Session
) -> None:
    _user(db)
    _user(db, "other@test.local")
    for _ in range(5):
        _attempt(client, "wrong")
    assert _attempt(client, "Right-Password1", "other@test.local") == 200
    logged = db.scalar(select(AuditLog.entity_id).where(AuditLog.action == "LOGIN_LOCKED"))
    assert logged == "guess@test.local"


def test_success_clears_the_count(client: TestClient, db: Session) -> None:
    _user(db)
    for _ in range(4):
        assert _attempt(client, "wrong") == 401
    assert _attempt(client, "Right-Password1") == 200
    assert [_attempt(client, "wrong") for _ in range(4)] == [401] * 4


def test_an_unknown_email_is_limited_the_same_way(client: TestClient) -> None:
    """The response must not reveal which emails exist."""
    assert [_attempt(client, "wrong", "nobody@test.local") for _ in range(5)] == [401] * 5
    assert _attempt(client, "wrong", "nobody@test.local") == 429


def test_the_lock_ends_when_the_window_passes() -> None:
    now = [1000.0]
    limiter = LoginLimiter(clock=lambda: now[0])
    for _ in range(5):
        limiter.record_failure("a", 5, 300)
    assert limiter.retry_after("a", 5, 300) > 0
    now[0] += 301
    assert limiter.retry_after("a", 5, 300) == 0


def test_only_the_failure_that_reaches_the_limit_reports_the_lock() -> None:
    limiter = LoginLimiter(clock=lambda: 0.0)
    assert [limiter.record_failure("a", 3, 300) for _ in range(3)] == [False, False, True]


@pytest.mark.parametrize(
    "attack",
    [
        "'; DROP TABLE contracts; --",
        "%' OR '1'='1",
        "\\",
        "%",
        "_",
    ],
)
def test_filters_treat_sql_as_plain_text(client: TestClient, db: Session, attack: str) -> None:
    sign_in(client, make_user(db, [Role.ADMIN]))
    for path in ("/contracts", "/reports/revenue-schedule", "/reports/journal-register"):
        response = client.get(f"/api/v1{path}", params={"contract": attack})
        assert response.status_code == 200, path
        assert response.json()["total"] == 0, path


def test_sorting_only_accepts_listed_columns(client: TestClient, db: Session) -> None:
    sign_in(client, make_user(db, [Role.ADMIN]))
    for path in ("/contracts", "/reports/revenue-schedule", "/reports/gl-summary"):
        response = client.get(f"/api/v1{path}", params={"sort": "password_hash; DROP TABLE users"})
        assert response.status_code == 422, path


def test_session_cookie_cannot_be_read_by_page_scripts(client: TestClient, db: Session) -> None:
    _user(db)
    response = client.post(LOGIN, json={"email": "guess@test.local", "password": "Right-Password1"})
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie


def test_password_hashes_never_leave_the_api(client: TestClient, db: Session) -> None:
    sign_in(client, make_user(db, [Role.ADMIN]))
    assert "password" not in client.get("/api/v1/users").text
    assert "password" not in client.get("/api/v1/auth/me").text
