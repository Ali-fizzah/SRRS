"""future period status and one-OPEN-period rule (task P1-T4)

Revision ID: 03fb5465290f
Revises: 6d9960ecb14d
Create Date: 2026-11-03

Seeding 2025-01..2028-12 needs a state for months after the current one; the
team chose a new FUTURE state, so the lifecycle is FUTURE -> OPEN -> CLOSING ->
CLOSED and closing a month opens the next FUTURE one.

- adds FUTURE to period_status;
- new periods default to FUTURE (a forgotten status can never create a second OPEN);
- a partial unique index allows at most one OPEN period (D6).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "03fb5465290f"
down_revision: str | None = "6d9960ecb14d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # PostgreSQL cannot use a new enum value in the transaction that adds it,
    # so this statement commits on its own before the default below uses it.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE period_status ADD VALUE IF NOT EXISTS 'FUTURE' BEFORE 'OPEN'")
    op.execute("ALTER TABLE accounting_periods ALTER COLUMN status SET DEFAULT 'FUTURE'")
    op.execute(
        "CREATE UNIQUE INDEX uq_accounting_periods_one_open "
        "ON accounting_periods (status) WHERE status = 'OPEN'"
    )


def downgrade() -> None:
    # PostgreSQL cannot drop an enum value, so the type is rebuilt without it.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM accounting_periods WHERE status = 'FUTURE') THEN
                RAISE EXCEPTION 'cannot downgrade: FUTURE accounting periods exist';
            END IF;
        END $$;
        """
    )
    op.execute("DROP INDEX uq_accounting_periods_one_open")
    op.execute("ALTER TABLE accounting_periods ALTER COLUMN status DROP DEFAULT")
    op.execute("ALTER TYPE period_status RENAME TO period_status_old")
    op.execute("CREATE TYPE period_status AS ENUM ('OPEN', 'CLOSING', 'CLOSED')")
    op.execute(
        "ALTER TABLE accounting_periods ALTER COLUMN status TYPE period_status "
        "USING status::text::period_status"
    )
    op.execute("ALTER TABLE accounting_periods ALTER COLUMN status SET DEFAULT 'OPEN'")
    op.execute("DROP TYPE period_status_old")
