"""Accounting periods, close workflow and engine runs (plan §8 Periods and Engine)."""

from fastapi import APIRouter

from app.api.v1.stubs import stub
from app.auth.roles import Role

router = APIRouter(prefix="/periods", tags=["periods"])

# §8 lists no role for reading periods; the dashboard shows the current period to everyone.
stub(router, "GET", "", None, "P5-T1")
stub(router, "GET", "/{key}/checklist", None, "P5-T1")
stub(router, "POST", "/{key}/start-close", Role.ACCOUNTANT, "P5-T1")
stub(router, "POST", "/{key}/close", Role.APPROVER, "P5-T1")
stub(router, "POST", "/{key}/reopen", Role.ADMIN, "P5-T1")

# Engine
stub(router, "POST", "/{key}/recognition-run", Role.ACCOUNTANT, "P2-T4")
stub(router, "POST", "/{key}/journals/generate", Role.ACCOUNTANT, "P4-T3")
