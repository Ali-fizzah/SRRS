"""Master data (plan §8 Master data: read UPLOADER, write ACCOUNTANT)."""

from fastapi import APIRouter

from app.api.v1.stubs import stub
from app.auth.roles import Role

router = APIRouter(tags=["master data"])

READ, WRITE = Role.UPLOADER, Role.ACCOUNTANT

stub(router, "GET", "/customers", READ, "P1-T11")

stub(router, "GET", "/products", READ, "P1-T11")
stub(router, "POST", "/products", WRITE, "P1-T11")
stub(router, "PATCH", "/products/{product_id}", WRITE, "P1-T11")
stub(router, "GET", "/products/{product_id}/ssp-history", READ, "P1-T11")

stub(router, "GET", "/gl-accounts", READ, "P1-T11")
stub(router, "POST", "/gl-accounts", WRITE, "P1-T11")
stub(router, "PATCH", "/gl-accounts/{account_id}", WRITE, "P1-T11")

stub(router, "GET", "/gl-mappings", READ, "P1-T11")
stub(router, "POST", "/gl-mappings", WRITE, "P1-T11")
stub(router, "PATCH", "/gl-mappings/{mapping_id}", WRITE, "P1-T11")
