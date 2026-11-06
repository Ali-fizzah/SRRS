"""Request and response bodies for /auth and /users (plan §8)."""

from typing import Annotated

from pydantic import AfterValidator, BaseModel, Field

from app.auth.passwords import MAX_PASSWORD_BYTES, password_problem
from app.auth.roles import Role

_EMAIL_SHAPE = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


def _check_password(value: str) -> str:
    if len(value.encode()) > MAX_PASSWORD_BYTES:
        raise ValueError(f"must be at most {MAX_PASSWORD_BYTES} bytes")
    problem = password_problem(value)
    if problem:
        raise ValueError(problem)
    return value


Email = Annotated[str, Field(pattern=_EMAIL_SHAPE, max_length=320), AfterValidator(str.lower)]
NewPassword = Annotated[str, AfterValidator(_check_password)]


class LoginRequest(BaseModel):
    email: Email
    password: str = Field(max_length=200)


class UserOut(BaseModel):
    id: int
    email: str
    full_name: str
    is_active: bool
    roles: list[Role]


class UserCreate(BaseModel):
    email: Email
    full_name: str = Field(min_length=1, max_length=255)
    password: NewPassword
    roles: list[Role] = Field(min_length=1)


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    password: NewPassword | None = None
    is_active: bool | None = None
    roles: list[Role] | None = Field(default=None, min_length=1)


class UserPage(BaseModel):
    items: list[UserOut]
    total: int
    page: int
    page_size: int
