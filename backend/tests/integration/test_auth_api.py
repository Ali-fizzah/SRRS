"""P1-T3: sign in with the JWT cookie, sign out, and session checks (D11)."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.auth.passwords import hash_password
from app.auth.roles import Role
from app.auth.tokens import create_access_token
from app.config import get_settings
from tests.integration.conftest import make_user, sign_in, use_token

PASSWORD = "Correct-Horse-9"
HASH = hash_password(PASSWORD)  # hashed once: bcrypt is slow on purpose
COOKIE = get_settings().cookie_name


@pytest.fixture
def accountant(db: Session):  # type: ignore[no-untyped-def]
    return make_user(db, [Role.ACCOUNTANT], email="acc@test.local", password_hash=HASH)


def test_login_sets_http_only_cookie_and_me_works(client: TestClient, accountant) -> None:  # type: ignore[no-untyped-def]
    response = client.post(
        "/api/v1/auth/login", json={"email": "ACC@test.local", "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
    assert response.json()["roles"] == ["ACCOUNTANT"]

    set_cookie = response.headers["set-cookie"]
    assert set_cookie.startswith(f"{COOKIE}=")
    assert "HttpOnly" in set_cookie
    assert "samesite=lax" in set_cookie.lower()

    me = client.get("/api/v1/auth/me")  # the client sends the cookie back
    assert me.status_code == 200
    assert me.json()["email"] == "acc@test.local"


@pytest.mark.parametrize(
    ("email", "password"),
    [("acc@test.local", "wrong-password"), ("nobody@test.local", PASSWORD)],
    ids=["wrong password", "unknown email"],
)
def test_bad_credentials_get_one_generic_error(
    client: TestClient,
    accountant,  # type: ignore[no-untyped-def]
    email: str,
    password: str,
) -> None:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 401
    assert response.json() == {
        "error": {
            "code": "INVALID_CREDENTIALS",
            "message": "Email or password is incorrect.",
            "details": None,
        }
    }
    assert "set-cookie" not in response.headers


def test_inactive_user_cannot_sign_in_or_use_old_session(client: TestClient, db: Session) -> None:
    user = make_user(db, [Role.ADMIN], email="gone@test.local", password_hash=HASH, is_active=False)
    response = client.post(
        "/api/v1/auth/login", json={"email": "gone@test.local", "password": PASSWORD}
    )
    assert response.status_code == 401
    sign_in(client, user)
    assert client.get("/api/v1/auth/me").status_code == 401


def test_logout_clears_the_cookie(client: TestClient, accountant) -> None:  # type: ignore[no-untyped-def]
    client.post("/api/v1/auth/login", json={"email": "acc@test.local", "password": PASSWORD})
    assert client.get("/api/v1/auth/me").status_code == 200

    response = client.post("/api/v1/auth/logout")
    assert response.status_code == 204
    assert f"{COOKIE}=" in response.headers["set-cookie"]
    assert client.get("/api/v1/auth/me").status_code == 401


@pytest.mark.parametrize(
    "make_token",
    [
        lambda uid: create_access_token(uid, now=datetime.now(UTC) - timedelta(days=2)),
        lambda uid: create_access_token(uid)[:-4] + "abcd",
        lambda uid: "not-a-jwt",
    ],
    ids=["expired", "tampered", "garbage"],
)
def test_invalid_session_tokens_are_rejected(
    client: TestClient,
    accountant,  # type: ignore[no-untyped-def]
    make_token,  # type: ignore[no-untyped-def]
) -> None:
    use_token(client, make_token(accountant.id))
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"
