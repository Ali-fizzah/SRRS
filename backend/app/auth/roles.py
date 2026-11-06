"""Roles and their ranking (plan D13, §8)."""

from collections.abc import Iterable
from enum import StrEnum


class Role(StrEnum):
    UPLOADER = "UPLOADER"
    ACCOUNTANT = "ACCOUNTANT"
    APPROVER = "APPROVER"
    ADMIN = "ADMIN"


# §8 gives every endpoint a *minimum* role, so roles form a ladder.
# D13 "Admin includes Approver" is the top two rungs of it.
RANK: dict[Role, int] = {
    Role.UPLOADER: 1,
    Role.ACCOUNTANT: 2,
    Role.APPROVER: 3,
    Role.ADMIN: 4,
}


def highest_rank(roles: Iterable[Role]) -> int:
    """A user with several roles counts as the highest one (0 = no role)."""
    return max((RANK[r] for r in roles), default=0)


def satisfies(roles: Iterable[Role], minimum: Role) -> bool:
    return highest_rank(roles) >= RANK[minimum]
