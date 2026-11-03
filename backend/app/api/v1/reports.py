"""Reports (plan §8 Reports: validation log UPLOADER, others ACCOUNTANT)."""

from fastapi import APIRouter

from app.api.v1.stubs import stub
from app.auth.roles import Role

router = APIRouter(prefix="/reports", tags=["reports"])

for _name in (
    "revenue-schedule",
    "deferred-rollforward",
    "recognized-vs-deferred",
    "journal-register",
    "gl-summary",
    "mrr-arr",
    "close-status",
):
    stub(router, "GET", f"/{_name}", Role.ACCOUNTANT, "P5-T3")
stub(router, "GET", "/validation-log", Role.UPLOADER, "P5-T3")
