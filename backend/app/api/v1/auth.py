"""Sign in, sign out and "who am I" (plan §8 Auth, D11)."""

from fastapi import APIRouter, Response
from sqlalchemy import select

from app.api.errors import ApiError
from app.auth.deps import AuthenticatedUser, DbSession, load_roles
from app.auth.passwords import verify_password
from app.auth.tokens import create_access_token
from app.config import get_settings
from app.models import User
from app.schemas.auth import LoginRequest, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_session_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        settings.cookie_name,
        token,
        max_age=settings.jwt_expire_minutes * 60,
        httponly=True,  # page JavaScript cannot read it
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


@router.post("/login", response_model=UserOut)
def login(body: LoginRequest, response: Response, db: DbSession) -> UserOut:
    """Public. Sets the session cookie on success."""
    user = db.scalar(select(User).where(User.email == body.email))
    password_ok = verify_password(body.password, user.password_hash if user else None)
    if user is None or not password_ok or not user.is_active:
        # One message for every failure, so it does not reveal which emails exist.
        raise ApiError(401, "INVALID_CREDENTIALS", "Email or password is incorrect.")
    _set_session_cookie(response, create_access_token(user.id))
    roles = sorted(load_roles(db, user.id))
    return UserOut(
        id=user.id, email=user.email, full_name=user.full_name, is_active=True, roles=roles
    )


@router.post("/logout", status_code=204)
def logout(response: Response) -> Response:
    """Public. Clears the session cookie (works even if already signed out)."""
    settings = get_settings()
    response.delete_cookie(
        settings.cookie_name,
        path="/",
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )
    response.status_code = 204
    return response


@router.get("/me", response_model=UserOut)
def me(user: AuthenticatedUser) -> UserOut:
    """Any signed-in user."""
    return UserOut(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        is_active=True,
        roles=sorted(user.roles),
    )
