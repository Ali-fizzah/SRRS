"""P1-T3: role ladder, password hashing and session tokens (no database)."""

from datetime import UTC, datetime, timedelta

import pytest

from app.auth.passwords import hash_password, verify_password
from app.auth.roles import Role, satisfies
from app.auth.tokens import create_access_token, read_user_id


@pytest.mark.parametrize(
    ("roles", "minimum", "expected"),
    [
        ([Role.ADMIN], Role.APPROVER, True),  # D13: Admin includes Approver
        ([Role.APPROVER], Role.ACCOUNTANT, True),
        ([Role.ACCOUNTANT], Role.APPROVER, False),
        ([Role.UPLOADER], Role.ACCOUNTANT, False),
        ([Role.UPLOADER, Role.APPROVER], Role.ACCOUNTANT, True),  # highest role counts
        ([], Role.UPLOADER, False),
    ],
)
def test_role_ladder(roles: list[Role], minimum: Role, expected: bool) -> None:
    assert satisfies(roles, minimum) is expected


def test_password_hash_round_trip() -> None:
    hashed = hash_password("s3cret-pass")
    assert hashed != "s3cret-pass" and hashed.startswith("$2")
    assert verify_password("s3cret-pass", hashed)
    assert not verify_password("s3cret-pasS", hashed)
    assert not verify_password("s3cret-pass", None)  # unknown user


def test_password_longer_than_bcrypt_limit_is_refused() -> None:
    with pytest.raises(ValueError):
        hash_password("x" * 73)
    assert not verify_password("x" * 73, hash_password("x" * 72))


def test_token_round_trip_and_expiry() -> None:
    assert read_user_id(create_access_token(42)) == 42
    stale = create_access_token(42, now=datetime.now(UTC) - timedelta(days=1))
    assert read_user_id(stale) is None
    assert read_user_id(create_access_token(42) + "x") is None
    assert read_user_id("garbage") is None
