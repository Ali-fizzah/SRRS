"""Version 1 routers, mounted under /api/v1 (plan §8). Every route declares its minimum role."""

from fastapi import APIRouter

from app.api.v1 import (
    auth,
    contracts,
    health,
    jobs,
    journals,
    master,
    periods,
    reports,
    templates,
    uploads,
    users,
)

api_router = APIRouter()
for _module in (
    health,
    auth,
    users,
    templates,
    uploads,
    master,
    contracts,
    periods,
    jobs,
    journals,
    reports,
):
    api_router.include_router(_module.router)
