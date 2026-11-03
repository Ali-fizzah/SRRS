"""Input template downloads (plan Â§8 Templates: UPLOADER)."""

from fastapi import APIRouter

from app.api.v1.stubs import stub
from app.auth.roles import Role

router = APIRouter(prefix="/templates", tags=["templates"])

stub(router, "GET", "", Role.UPLOADER, "P1-T5")
stub(router, "GET", "/{name}", Role.UPLOADER, "P1-T5")
