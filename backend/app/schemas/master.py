"""Response bodies for master data (plan §8). Money is Decimal: a string in the JSON (D1)."""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel

from app.models.enums import AccountRole, GlAccountType, RecognitionMethod, SspSource


class CustomerOut(BaseModel):
    id: int
    customer_code: str
    name: str
    country: str
    source_upload_id: int | None
    source_row: int | None


class ProductOut(BaseModel):
    id: int
    product_code: str
    name: str
    category: str | None
    list_price: Decimal
    recognition_method: RecognitionMethod
    is_separate_obligation: bool
    revenue_account: str
    # The latest SSP rule; GET /products/{id}/ssp-history has them all.
    ssp_source: SspSource | None
    ssp_value: Decimal | None
    ssp_pct: Decimal | None
    source_upload_id: int | None
    source_row: int | None


class SspRuleOut(BaseModel):
    id: int
    ssp_source: SspSource
    ssp_value: Decimal | None
    ssp_pct: Decimal | None
    valid_from: date
    valid_to: date | None
    source_upload_id: int | None
    source_row: int | None


class GlAccountOut(BaseModel):
    id: int
    account_code: str
    name: str
    type: GlAccountType
    is_active: bool


class GlMappingOut(BaseModel):
    """D12: product set = product mapping; category set = category mapping; neither = default."""

    id: int
    account_role: AccountRole
    product_code: str | None
    product_category: str | None
    account_code: str
    account_name: str
