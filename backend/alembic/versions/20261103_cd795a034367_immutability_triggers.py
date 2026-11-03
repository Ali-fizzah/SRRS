"""immutability triggers: database-enforced rules of plan §6.3 (task P1-T2)

Revision ID: cd795a034367
Revises: 9bf3a015d454
Create Date: 2026-11-03

The SQL is inline on purpose: a migration must not change after it is applied
(CLAUDE.md rule 7), so it cannot read a file that might be edited later.

Error codes (mirrored in app/db/errors.py):
  RV001  journal entry, line or batch is POSTED (read-only, plan §5.7 / §6.3)
  RV002  batch cannot be POSTED: debits <> credits
  RV003  period is CLOSED: no new journal batch
  RV004  schedule line is POSTED
  RV005  table is append-only (contract_versions, audit_log)
"""

from collections.abc import Sequence

from alembic import op

revision: str = "cd795a034367"
down_revision: str | None = "9bf3a015d454"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


FUNCTIONS = """
-- Rule 1 (+ §5.7): entries of a POSTED batch cannot be changed, removed or added to.
CREATE FUNCTION revrec_guard_journal_entry() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        IF EXISTS (SELECT 1 FROM journal_batches WHERE id = OLD.batch_id AND status = 'POSTED') THEN
            RAISE EXCEPTION 'journal entry % is in a POSTED batch and cannot be changed', OLD.id
                USING ERRCODE = 'RV001',
                      HINT = 'Book a REVERSAL or ADJUSTMENT entry in the current open period.';
        END IF;
    END IF;
    IF TG_OP IN ('INSERT', 'UPDATE') THEN
        IF EXISTS (SELECT 1 FROM journal_batches WHERE id = NEW.batch_id AND status = 'POSTED') THEN
            RAISE EXCEPTION 'journal batch % is POSTED; entries cannot be added to it', NEW.batch_id
                USING ERRCODE = 'RV001';
        END IF;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

-- Rule 1: lines of an entry in a POSTED batch cannot be changed, removed or added to.
CREATE FUNCTION revrec_guard_journal_line() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        IF EXISTS (
            SELECT 1 FROM journal_entries e JOIN journal_batches b ON b.id = e.batch_id
            WHERE e.id = OLD.entry_id AND b.status = 'POSTED'
        ) THEN
            RAISE EXCEPTION 'journal line % is in a POSTED batch and cannot be changed', OLD.id
                USING ERRCODE = 'RV001',
                      HINT = 'Book a REVERSAL or ADJUSTMENT entry in the current open period.';
        END IF;
    END IF;
    IF TG_OP IN ('INSERT', 'UPDATE') THEN
        IF EXISTS (
            SELECT 1 FROM journal_entries e JOIN journal_batches b ON b.id = e.batch_id
            WHERE e.id = NEW.entry_id AND b.status = 'POSTED'
        ) THEN
            RAISE EXCEPTION 'journal entry % is in a POSTED batch; lines cannot be added to it',
                NEW.entry_id
                USING ERRCODE = 'RV001';
        END IF;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

-- Rules 2 and 3, and §5.7 "POSTED is read-only" for the batch row itself.
CREATE FUNCTION revrec_guard_journal_batch() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_debit numeric(18, 2);
    v_credit numeric(18, 2);
BEGIN
    IF TG_OP IN ('UPDATE', 'DELETE') AND OLD.status = 'POSTED' THEN
        RAISE EXCEPTION 'journal batch % is POSTED and read-only', OLD.id
            USING ERRCODE = 'RV001';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;

    IF TG_OP = 'INSERT' OR NEW.period_id IS DISTINCT FROM OLD.period_id THEN
        IF EXISTS (SELECT 1 FROM accounting_periods WHERE id = NEW.period_id AND status = 'CLOSED') THEN
            RAISE EXCEPTION 'accounting period % is CLOSED; no journal batch can be added',
                NEW.period_id
                USING ERRCODE = 'RV003';
        END IF;
    END IF;

    IF NEW.status = 'POSTED' THEN
        SELECT coalesce(sum(l.debit), 0), coalesce(sum(l.credit), 0)
          INTO v_debit, v_credit
          FROM journal_lines l JOIN journal_entries e ON e.id = l.entry_id
         WHERE e.batch_id = NEW.id;
        IF v_debit <> v_credit THEN
            RAISE EXCEPTION 'journal batch % cannot be POSTED: debits % <> credits %',
                NEW.id, v_debit, v_credit
                USING ERRCODE = 'RV002';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

-- Rule 4: posted schedule lines are history.
CREATE FUNCTION revrec_guard_schedule_line() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.status = 'POSTED' THEN
        RAISE EXCEPTION 'schedule line % is POSTED and cannot be changed', OLD.id
            USING ERRCODE = 'RV004';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

-- Rule 5: append-only tables.
CREATE FUNCTION revrec_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% is append-only: rows cannot be updated or deleted', TG_TABLE_NAME
        USING ERRCODE = 'RV005';
END;
$$;
"""

TRIGGERS = """
CREATE TRIGGER trg_journal_entries_guard
    BEFORE INSERT OR UPDATE OR DELETE ON journal_entries
    FOR EACH ROW EXECUTE FUNCTION revrec_guard_journal_entry();

CREATE TRIGGER trg_journal_lines_guard
    BEFORE INSERT OR UPDATE OR DELETE ON journal_lines
    FOR EACH ROW EXECUTE FUNCTION revrec_guard_journal_line();

CREATE TRIGGER trg_journal_batches_guard
    BEFORE INSERT OR UPDATE OR DELETE ON journal_batches
    FOR EACH ROW EXECUTE FUNCTION revrec_guard_journal_batch();

CREATE TRIGGER trg_schedule_lines_guard
    BEFORE UPDATE OR DELETE ON schedule_lines
    FOR EACH ROW EXECUTE FUNCTION revrec_guard_schedule_line();

CREATE TRIGGER trg_contract_versions_append_only
    BEFORE UPDATE OR DELETE ON contract_versions
    FOR EACH ROW EXECUTE FUNCTION revrec_append_only();

CREATE TRIGGER trg_audit_log_append_only
    BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION revrec_append_only();
"""

DROP = """
DROP TRIGGER IF EXISTS trg_audit_log_append_only ON audit_log;
DROP TRIGGER IF EXISTS trg_contract_versions_append_only ON contract_versions;
DROP TRIGGER IF EXISTS trg_schedule_lines_guard ON schedule_lines;
DROP TRIGGER IF EXISTS trg_journal_batches_guard ON journal_batches;
DROP TRIGGER IF EXISTS trg_journal_lines_guard ON journal_lines;
DROP TRIGGER IF EXISTS trg_journal_entries_guard ON journal_entries;
DROP FUNCTION IF EXISTS revrec_append_only();
DROP FUNCTION IF EXISTS revrec_guard_schedule_line();
DROP FUNCTION IF EXISTS revrec_guard_journal_batch();
DROP FUNCTION IF EXISTS revrec_guard_journal_line();
DROP FUNCTION IF EXISTS revrec_guard_journal_entry();
"""


def upgrade() -> None:
    op.execute(FUNCTIONS)
    op.execute(TRIGGERS)


def downgrade() -> None:
    op.execute(DROP)
