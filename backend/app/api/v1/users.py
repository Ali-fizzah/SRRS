"""User administration (plan §8 Users: ADMIN). Every change writes audit_log."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.api.errors import ApiError
from app.audit import write_audit
from app.auth.deps import CurrentUser, DbSession, load_roles, require_role
from app.auth.passwords import hash_password
from app.auth.roles import Role
from app.models import Role as RoleRow
from app.models import User, UserRole
from app.schemas.auth import UserCreate, UserOut, UserPage, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])
Admin = Annotated[CurrentUser, Depends(require_role(Role.ADMIN))]


def _out(db: Session, user: User) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        is_active=user.is_active,
        roles=sorted(load_roles(db, user.id)),
    )


def _snapshot(out: UserOut) -> dict[str, Any]:
    """What the audit log keeps about a user (never the password hash)."""
    return out.model_dump(mode="json")


def _set_roles(db: Session, user_id: int, roles: list[Role]) -> None:
    role_ids = dict(db.execute(select(RoleRow.name, RoleRow.id)).tuples().all())
    db.execute(delete(UserRole).where(UserRole.user_id == user_id))
    for role in sorted(set(roles)):
        db.add(UserRole(user_id=user_id, role_id=role_ids[role.value]))


@router.get("", response_model=UserPage)
def list_users(
    db: DbSession,
    _: Admin,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> UserPage:
    total = db.scalar(select(func.count()).select_from(User)) or 0
    users = db.scalars(
        select(User).order_by(User.email).offset((page - 1) * page_size).limit(page_size)
    )
    return UserPage(items=[_out(db, u) for u in users], total=total, page=page, page_size=page_size)


@router.post("", response_model=UserOut, status_code=201)
def create_user(body: UserCreate, db: DbSession, admin: Admin) -> UserOut:
    if db.scalar(select(User.id).where(User.email == body.email)) is not None:
        raise ApiError(409, "EMAIL_TAKEN", f"A user with email {body.email} already exists.")
    user = User(
        email=body.email, full_name=body.full_name, password_hash=hash_password(body.password)
    )
    db.add(user)
    db.flush()
    _set_roles(db, user.id, body.roles)
    db.flush()
    out = _out(db, user)
    write_audit(
        db,
        user_id=admin.id,
        action="USER_CREATED",
        entity_type="user",
        entity_id=user.id,
        after=_snapshot(out),
    )
    db.commit()
    return out


@router.patch("/{user_id}", response_model=UserOut)
def update_user(user_id: int, body: UserUpdate, db: DbSession, admin: Admin) -> UserOut:
    user = db.get(User, user_id)
    if user is None:
        raise ApiError(404, "NOT_FOUND", f"User {user_id} does not exist.")
    if user.id == admin.id and (
        body.is_active is False or (body.roles is not None and Role.ADMIN not in body.roles)
    ):
        raise ApiError(
            409, "SELF_LOCKOUT", "You cannot deactivate yourself or remove your own ADMIN role."
        )

    before = _snapshot(_out(db, user))
    if body.full_name is not None:
        user.full_name = body.full_name
    if body.is_active is not None:
        user.is_active = body.is_active
    if body.password is not None:
        user.password_hash = hash_password(body.password)
    if body.roles is not None:
        _set_roles(db, user.id, body.roles)
    db.flush()
    out = _out(db, user)
    write_audit(
        db,
        user_id=admin.id,
        action="USER_PASSWORD_RESET" if body.password is not None else "USER_UPDATED",
        entity_type="user",
        entity_id=user.id,
        before=before,
        after=_snapshot(out),
    )
    db.commit()
    return out
