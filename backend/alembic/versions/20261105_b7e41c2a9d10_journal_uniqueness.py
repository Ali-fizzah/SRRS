"""journal uniqueness: a document is booked once and an entry is reversed once (P4-T3, P4-T4)

Revision ID: b7e41c2a9d10
Revises: 03fb5465290f
Create Date: 2026-11-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b7e41c2a9d10"
down_revision: str | None = "03fb5465290f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "uq_journal_entries_one_per_document",
        "journal_entries",
        ["entry_type", "source_id"],
        unique=True,
        postgresql_where=sa.text("entry_type IN ('INVOICE', 'CREDIT_NOTE')"),
    )
    op.create_index(
        "uq_journal_entries_one_reversal",
        "journal_entries",
        ["reverses_entry_id"],
        unique=True,
        postgresql_where=sa.text("reverses_entry_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_journal_entries_one_reversal", table_name="journal_entries")
    op.drop_index("uq_journal_entries_one_per_document", table_name="journal_entries")
