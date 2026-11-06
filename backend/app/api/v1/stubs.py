"""Placeholder endpoints: the §8 route and its role check exist now; behaviour comes later."""

import re
from typing import Any

from fastapi import APIRouter, Depends

from app.api.errors import not_implemented
from app.auth.deps import get_current_user, require_role
from app.auth.roles import Role


def stub(router: APIRouter, method: str, path: str, minimum: Role | None, task: str) -> None:
    """Add `method path` to `router`. `minimum=None` means any signed-in user."""
    guard: Any = require_role(minimum) if minimum is not None else get_current_user

    def endpoint() -> None:
        raise not_implemented(task)

    full = f"{router.prefix}{path}"
    name = f"{method.lower()}_{re.sub(r'[^a-z0-9]+', '_', full.lower()).strip('_')}"
    router.add_api_route(
        path,
        endpoint,
        methods=[method],
        name=name,
        dependencies=[Depends(guard)],
        status_code=501,
        summary=f"Built in {task}",
    )
