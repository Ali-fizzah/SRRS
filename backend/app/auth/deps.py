"""FastAPI dependencies that identify the caller and enforce roles (plan §8, D11, D13).

Roles are read from the database on every request, so deactivating a user or
changing their roles takes effect immediately, not when their token expires.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.errors import ApiError
from app.auth.roles import Role, satisfies
from app.auth.tokens import read_user_id
from app.config import get_settings
from app.db.session import get_db
from app.models import Role as RoleRow
from app.models import User, UserRole

DbSession = Annotated[Session, Depends(get_db)]


@dataclass(frozen=True)
class CurrentUser:
    id: int
    email: str
    full_name: str
    roles: frozenset[Role]


def load_roles(db: Session, user_id: int) -> frozenset[Role]:
    names = db.scalars(
        select(RoleRow.name)
        .join(UserRole, UserRole.role_id == RoleRow.id)
        .where(UserRole.user_id == user_id)
    )
    return frozenset(Role(n) for n in names)


def get_current_user(request: Request, db: DbSession) -> CurrentUser:
    token = request.cookies.get(get_settings().cookie_name)
    user_id = read_user_id(token) if token else None
    user = db.get(User, user_id) if user_id is not None else None
    if user is None or not user.is_active:
        raise ApiError(401, "UNAUTHENTICATED", "Sign in to continue.")
    return CurrentUser(user.id, user.email, user.full_name, load_roles(db, user.id))


AuthenticatedUser = Annotated[CurrentUser, Depends(get_current_user)]


def require_role(minimum: Role) -> Callable[[CurrentUser], CurrentUser]:
    """Dependency: the caller must hold `minimum` or a higher role."""

    def check(user: AuthenticatedUser) -> CurrentUser:
        if not satisfies(user.roles, minimum):
            raise ApiError(403, "FORBIDDEN", f"This action needs the {minimum.value} role.")
        return user

    check.minimum_role = minimum  # type: ignore[attr-defined]  # read by the role-matrix test
    return check
