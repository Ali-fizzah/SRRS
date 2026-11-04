"""Master data (plan §8 Master data: read UPLOADER, write ACCOUNTANT)."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select

from app.api.errors import ApiError
from app.api.listing import Listing, Page, apply_sort, list_response
from app.api.v1.stubs import stub
from app.auth.deps import DbSession, require_role
from app.auth.roles import Role
from app.models import Customer, GlAccount, GlMapping, Product, SspRule
from app.schemas.master import CustomerOut, GlAccountOut, GlMappingOut, ProductOut, SspRuleOut

router = APIRouter(tags=["master data"])

READ, WRITE = Role.UPLOADER, Role.ACCOUNTANT
CanRead = [Depends(require_role(READ))]
CSV: dict[int | str, dict[str, Any]] = {200: {"content": {"text/csv": {}}}}
Search = Annotated[str | None, Query(min_length=1, max_length=128)]

# §8 and §9 include editing, but P1-T11 is read-only and no §12 task schedules it yet.
EDITING = "master-data editing (not yet scheduled in plan §12)"


@router.get("/customers", response_model=Page[CustomerOut], responses=CSV, dependencies=CanRead)
def list_customers(db: DbSession, params: Listing, customer: Search = None) -> Any:
    statement = select(
        Customer.id,
        Customer.customer_code,
        Customer.name,
        Customer.country,
        Customer.source_upload_id,
        Customer.source_row,
    )
    if customer is not None:
        statement = statement.where(
            or_(
                Customer.customer_code.icontains(customer, autoescape=True),
                Customer.name.icontains(customer, autoescape=True),
            )
        )
    statement = apply_sort(
        statement,
        params.sort,
        {
            "customer_code": Customer.customer_code,
            "name": Customer.name,
            "country": Customer.country,
        },
        [Customer.customer_code],
    )
    return list_response(db, statement, params, CustomerOut, "customers.csv")


@router.get("/products", response_model=Page[ProductOut], responses=CSV, dependencies=CanRead)
def list_products(db: DbSession, params: Listing, product: Search = None) -> Any:
    latest_rule = (
        select(SspRule.product_id, SspRule.ssp_source, SspRule.ssp_value, SspRule.ssp_pct)
        .distinct(SspRule.product_id)
        .order_by(SspRule.product_id, SspRule.valid_from.desc(), SspRule.id.desc())
        .subquery()
    )
    statement = (
        select(
            Product.id,
            Product.product_code,
            Product.name,
            Product.category,
            Product.list_price,
            Product.recognition_method,
            Product.is_separate_obligation,
            GlAccount.account_code.label("revenue_account"),
            latest_rule.c.ssp_source,
            latest_rule.c.ssp_value,
            latest_rule.c.ssp_pct,
            Product.source_upload_id,
            Product.source_row,
        )
        .join(GlAccount, GlAccount.id == Product.revenue_account_id)
        .outerjoin(latest_rule, latest_rule.c.product_id == Product.id)
    )
    if product is not None:
        statement = statement.where(
            or_(
                Product.product_code.icontains(product, autoescape=True),
                Product.name.icontains(product, autoescape=True),
            )
        )
    statement = apply_sort(
        statement,
        params.sort,
        {
            "product_code": Product.product_code,
            "name": Product.name,
            "category": Product.category,
            "list_price": Product.list_price,
            "recognition_method": Product.recognition_method,
            "is_separate_obligation": Product.is_separate_obligation,
            "revenue_account": GlAccount.account_code,
        },
        [Product.product_code],
    )
    return list_response(db, statement, params, ProductOut, "products.csv")


@router.get(
    "/products/{product_id}/ssp-history",
    response_model=Page[SspRuleOut],
    responses=CSV,
    dependencies=CanRead,
)
def list_ssp_history(product_id: int, db: DbSession, params: Listing) -> Any:
    """Every SSP rule of a product, newest first; rules are added, never overwritten (§5.2)."""
    if db.get(Product, product_id) is None:
        raise ApiError(404, "NOT_FOUND", f"Product {product_id} does not exist.")
    statement = select(
        SspRule.id,
        SspRule.ssp_source,
        SspRule.ssp_value,
        SspRule.ssp_pct,
        SspRule.valid_from,
        SspRule.valid_to,
        SspRule.source_upload_id,
        SspRule.source_row,
    ).where(SspRule.product_id == product_id)
    statement = apply_sort(
        statement,
        params.sort,
        {"valid_from": SspRule.valid_from, "ssp_source": SspRule.ssp_source},
        [SspRule.valid_from.desc(), SspRule.id.desc()],
    )
    return list_response(db, statement, params, SspRuleOut, f"product_{product_id}_ssp.csv")


@router.get("/gl-accounts", response_model=Page[GlAccountOut], responses=CSV, dependencies=CanRead)
def list_gl_accounts(db: DbSession, params: Listing) -> Any:
    statement = select(
        GlAccount.id, GlAccount.account_code, GlAccount.name, GlAccount.type, GlAccount.is_active
    )
    statement = apply_sort(
        statement,
        params.sort,
        {
            "account_code": GlAccount.account_code,
            "name": GlAccount.name,
            "type": GlAccount.type,
            "is_active": GlAccount.is_active,
        },
        [GlAccount.account_code],
    )
    return list_response(db, statement, params, GlAccountOut, "gl_accounts.csv")


@router.get("/gl-mappings", response_model=Page[GlMappingOut], responses=CSV, dependencies=CanRead)
def list_gl_mappings(db: DbSession, params: Listing, product: Search = None) -> Any:
    statement = (
        select(
            GlMapping.id,
            GlMapping.account_role,
            Product.product_code,
            GlMapping.product_category,
            GlAccount.account_code,
            GlAccount.name.label("account_name"),
        )
        .join(GlAccount, GlAccount.id == GlMapping.account_id)
        .outerjoin(Product, Product.id == GlMapping.product_id)
    )
    if product is not None:
        statement = statement.where(Product.product_code.icontains(product, autoescape=True))
    statement = apply_sort(
        statement,
        params.sort,
        {
            "account_role": GlMapping.account_role,
            "product_code": Product.product_code,
            "product_category": GlMapping.product_category,
            "account_code": GlAccount.account_code,
        },
        [GlMapping.account_role, GlMapping.id],
    )
    return list_response(db, statement, params, GlMappingOut, "gl_mappings.csv")


stub(router, "POST", "/products", WRITE, EDITING)
stub(router, "PATCH", "/products/{product_id}", WRITE, EDITING)
stub(router, "POST", "/gl-accounts", WRITE, EDITING)
stub(router, "PATCH", "/gl-accounts/{account_id}", WRITE, EDITING)
stub(router, "POST", "/gl-mappings", WRITE, EDITING)
stub(router, "PATCH", "/gl-mappings/{mapping_id}", WRITE, EDITING)
