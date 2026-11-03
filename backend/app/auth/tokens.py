"""Session tokens: a signed JWT carrying the user id, stored in an httpOnly cookie (D11)."""

from datetime import UTC, datetime, timedelta

import jwt

from app.config import get_settings

ALGORITHM = "HS256"


def create_access_token(user_id: int, *, now: datetime | None = None) -> str:
    settings = get_settings()
    issued = now or datetime.now(UTC)
    claims = {
        "sub": str(user_id),
        "iat": issued,
        "exp": issued + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(claims, settings.jwt_secret, algorithm=ALGORITHM)


def read_user_id(token: str) -> int | None:
    """User id from a valid, unexpired token; None for anything else."""
    try:
        claims = jwt.decode(
            token,
            get_settings().jwt_secret,
            algorithms=[ALGORITHM],
            options={"require": ["sub", "exp", "iat"]},
        )
        return int(claims["sub"])
    except (jwt.InvalidTokenError, ValueError):
        return None
