"""Posting rules and GL account resolution (plan §5.6, §5.7, D12). Pure: integer cents.

`position` is one contract's running billed minus recognised: positive is deferred revenue,
negative is an unbilled receivable (§5.6).
"""

from collections.abc import Collection, Iterable
from dataclasses import dataclass


def split_invoice(position: int, amount: int) -> tuple[int, int]:
    """§5.6 invoice: (credit to UNBILLED_AR up to its balance, remainder to DEFERRED_REVENUE)."""
    unbilled = min(max(-position, 0), amount)
    return unbilled, amount - unbilled


def split_revenue(position: int, amount: int) -> tuple[int, int]:
    """§5.6 revenue: (debit to DEFERRED_REVENUE up to its balance, remainder to UNBILLED_AR)."""
    deferred = min(max(position, 0), amount)
    return deferred, amount - deferred


def position_effect(
    entry_type: str, reversed_type: str | None, total_debit: int, revenue_net_credit: int
) -> int:
    """How much one journal entry moves the position.

    `total_debit` is the entry's total; `revenue_net_credit` is its credits minus debits on
    revenue accounts. A reversal moves it the opposite way from the entry it mirrors.
    """
    kind = reversed_type if entry_type == "REVERSAL" else entry_type
    if kind in ("REVENUE", "REVENUE_CATCH_UP"):
        return -revenue_net_credit  # already opposite for a reversal, which debits revenue
    sign = -1 if entry_type == "REVERSAL" else 1
    if kind == "INVOICE":
        return sign * total_debit
    if kind == "CREDIT_NOTE":
        return -sign * total_debit
    raise ValueError(f"no position rule for entry type {kind}")


class MissingMappingError(ValueError):
    """D12: no usable GL account for this role and product."""

    def __init__(self, role: str, product_code: str | None, detail: str = "no mapping") -> None:
        subject = f"product {product_code}" if product_code else "this document"
        super().__init__(f"{detail} for role {role} on {subject}")
        self.role = role
        self.product_code = product_code


@dataclass(frozen=True)
class MappingRow:
    role: str
    product_id: int | None
    category: str | None
    account_id: int


@dataclass(frozen=True)
class ProductAccounts:
    """What resolving an account needs to know about a product."""

    product_id: int
    product_code: str
    category: str | None
    revenue_account_id: int


class GlResolver:
    """D12: role -> account, with precedence product > category > default.

    A product's own revenue account (products template, §7) counts as its product-level REVENUE
    mapping; a mapping row written for that exact product overrides it.
    """

    def __init__(self, rows: Iterable[MappingRow], active_accounts: Collection[int]) -> None:
        self._by_product: dict[tuple[str, int], int] = {}
        self._by_category: dict[tuple[str, str], int] = {}
        self._default: dict[str, int] = {}
        self._active = frozenset(active_accounts)
        for row in rows:
            if row.product_id is not None:
                self._by_product[(row.role, row.product_id)] = row.account_id
            elif row.category is not None:
                self._by_category[(row.role, row.category)] = row.account_id
            else:
                self._default[row.role] = row.account_id

    def account(self, role: str, product: ProductAccounts | None) -> int:
        """The account for `role`. `product` is None when a document names no product."""
        code = product.product_code if product else None
        found = self._find(role, product)
        if found is None:
            raise MissingMappingError(role, code)
        if found not in self._active:
            raise MissingMappingError(role, code, f"inactive account {found}")
        return found

    def _find(self, role: str, product: ProductAccounts | None) -> int | None:
        if product is not None:
            mapped = self._by_product.get((role, product.product_id))
            if mapped is not None:
                return mapped
            if role == "REVENUE":
                return product.revenue_account_id
            if product.category is not None:
                mapped = self._by_category.get((role, product.category))
                if mapped is not None:
                    return mapped
        return self._default.get(role)
