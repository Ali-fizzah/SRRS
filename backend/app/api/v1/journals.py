"""Journal batches and entries (plan §8 Journals: view ACCOUNTANT, approve/post APPROVER)."""

from fastapi import APIRouter

from app.api.v1.stubs import stub
from app.auth.roles import Role

router = APIRouter(tags=["journals"])

stub(router, "GET", "/journal-batches", Role.ACCOUNTANT, "P4-T4")
stub(router, "GET", "/journal-batches/{batch_id}", Role.ACCOUNTANT, "P4-T4")
stub(router, "POST", "/journal-batches/{batch_id}/approve", Role.APPROVER, "P4-T4")
stub(router, "POST", "/journal-batches/{batch_id}/send-back", Role.APPROVER, "P4-T4")
stub(router, "POST", "/journal-batches/{batch_id}/post", Role.APPROVER, "P4-T4")
# A reversal is a new entry that still goes through approve/post, so the preparer
# (ACCOUNTANT) books it and an APPROVER approves it.
stub(router, "POST", "/journal-entries/{entry_id}/reverse", Role.ACCOUNTANT, "P4-T4")
