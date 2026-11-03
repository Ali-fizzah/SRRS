"""Contracts and their drill-down tabs (plan §8 Contracts: UPLOADER)."""

from fastapi import APIRouter

from app.api.v1.stubs import stub
from app.auth.roles import Role

router = APIRouter(prefix="/contracts", tags=["contracts"])

stub(router, "GET", "", Role.UPLOADER, "P2-T4")
stub(router, "GET", "/{contract_id}", Role.UPLOADER, "P3-T6")
stub(router, "GET", "/{contract_id}/versions/{version_no}", Role.UPLOADER, "P3-T6")
stub(router, "GET", "/{contract_id}/schedule", Role.UPLOADER, "P2-T4")
stub(router, "GET", "/{contract_id}/billing", Role.UPLOADER, "P3-T6")
stub(router, "GET", "/{contract_id}/journal-lines", Role.UPLOADER, "P4-T4")
stub(router, "GET", "/{contract_id}/source-rows", Role.UPLOADER, "P3-T6")
