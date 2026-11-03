"""File uploads and their validation logs (plan §8 Uploads: UPLOADER)."""

from fastapi import APIRouter

from app.api.v1.stubs import stub
from app.auth.roles import Role

router = APIRouter(prefix="/uploads", tags=["uploads"])

stub(router, "POST", "", Role.UPLOADER, "P1-T9")
stub(router, "GET", "", Role.UPLOADER, "P1-T10")
stub(router, "GET", "/{upload_id}", Role.UPLOADER, "P1-T10")
stub(router, "GET", "/{upload_id}/errors", Role.UPLOADER, "P1-T10")
stub(router, "GET", "/{upload_id}/file", Role.UPLOADER, "P1-T10")
