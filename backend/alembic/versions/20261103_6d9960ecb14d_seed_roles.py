"""seed roles: the four roles of plan D13 (task P1-T3)

Revision ID: 6d9960ecb14d
Revises: cd795a034367
Create Date: 2026-11-03

The role names are fixed by D13 and the code depends on them, so they are
reference data created by a migration, not editable seed data.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "6d9960ecb14d"
down_revision: str | None = "cd795a034367"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLES = ("UPLOADER", "ACCOUNTANT", "APPROVER", "ADMIN")


def upgrade() -> None:
    roles = sa.table("roles", sa.column("name", sa.String))
    op.bulk_insert(roles, [{"name": name} for name in ROLES])


def downgrade() -> None:
    bind = op.get_bind()
    names = {"names": list(ROLES)}
    bind.execute(
        sa.text(
            "DELETE FROM user_roles WHERE role_id IN "
            "(SELECT id FROM roles WHERE name = ANY(:names))"
        ),
        names,
    )
    bind.execute(sa.text("DELETE FROM roles WHERE name = ANY(:names)"), names)
