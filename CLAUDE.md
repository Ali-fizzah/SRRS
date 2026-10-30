# CLAUDE.md — Revenue Recognition System (FYP)

Web-based revenue sub-ledger for subscription contracts (simplified ASC 606 / IFRS 15). Users upload contract and billing files; the system validates them, allocates price by relative SSP, generates revenue schedules, books balanced journals, closes periods and reports. **Outputs must match the Excel benchmarks within 0.01.**

**The full specification and task list is `docs/DEVELOPMENT_PLAN.md`. Read the relevant sections before every task.**

## How to work in this repo

- Work on **one task ID** from `docs/DEVELOPMENT_PLAN.md` §12 at a time (e.g. `P3-T2`). Read the task's *Read first* sections, then show a short plan before writing code.
- A task is done only when its acceptance criteria pass and §13 *Definition of Done* holds.
- If the plan does not answer an accounting question, **stop and ask**. Do not invent accounting rules. Decisions live in plan §2 and `docs/accounting-rules.md`.
- Branch: `feat/<task-id>-<slug>`. Commit messages start with the task ID.
- Anything in plan §15 (out of scope) is not built; note ideas in `docs/future-work.md`.

## Commands

```bash
make dev          # docker-compose: postgres, api (FastAPI), worker, web (Next.js)
make migrate      # alembic upgrade head
make seed         # admin user, chart of accounts, GL mappings, periods
make test         # backend unit + integration tests
make bench        # golden benchmark replay (benchmarks/cases/*) — must stay green
make lint         # ruff + mypy (backend), eslint + tsc (frontend)
make load N=50000 # performance run (Phase 7)
```

Backend only: `cd backend && pytest tests/unit -q`. Frontend only: `cd frontend && npm run lint && npm run typecheck`.

## Architecture map

- `backend/app/engine/` — **pure** accounting functions (allocation, recognition methods, events, balances). No DB, no I/O, no clock. Integer cents in, integer cents out.
- `backend/app/services/` — orchestration that loads from DB, calls the engine, writes results (recognition run, journal generation, period close).
- `backend/app/ingestion/` — template registry, parsers, validators (error codes E001–E014), loaders.
- `backend/app/api/v1/` — FastAPI routers; every route declares its minimum role.
- `backend/app/jobs/` — Postgres-backed job queue and worker (no Redis).
- `frontend/src/app/` — Next.js App Router pages; MUI community components only.
- `benchmarks/cases/<ID>/` — `inputs/`, `expected/`, `case.yaml`. `benchmarks/source/` holds the Excel workbooks.

## Non-negotiable rules

1. **Money:** integer cents in the engine, `NUMERIC(18,2)` in Postgres, `Decimal`/string at the API. Never use `float` for money.
2. **Rounding:** `ROUND_HALF_UP`, 2 dp. Allocation plug → largest SSP (tie: lowest line no). Ratable daily → cumulative rounding. Ratable monthly → equal months, last month absorbs the difference. (Plan §5.2–5.3.)
3. **Immutability:** never update or delete posted journals, posted schedule lines, contract versions or audit log rows. Corrections are new reversal/adjustment entries in the current open period. DB triggers enforce this — do not disable them.
4. **Versioning:** contract events create a new version; only `PENDING` schedule lines are superseded.
5. **Traceability:** every imported row keeps `source_upload_id`, `source_row`, `source_payload`; every journal entry keeps contract, version and source document ids.
6. **Benchmarks:** never edit a file under `benchmarks/cases/*/expected/` to make a test pass. Report the variance instead.
7. **Schema:** change it only with a new Alembic migration. Never edit an applied migration.
8. **Security:** every endpoint enforces roles (`UPLOADER`, `ACCOUNTANT`, `APPROVER`, `ADMIN`); every state change writes `audit_log`. No string-formatted SQL with user input.
9. **Ingestion:** read uploaded files with every column as string (IDs have leading zeros), then parse types explicitly.
10. **MUI:** community/MIT packages only (`@mui/material`, `@mui/x-data-grid`, `@mui/x-charts`, `@mui/x-date-pickers`). Pagination, filtering, aggregation and CSV export are server-side.

## Code style

- Python 3.12, type hints everywhere, `mypy --strict` on `engine/`. ruff for lint and format. Pydantic v2 schemas, SQLAlchemy 2.0 typed models.
- TypeScript strict; API types generated from FastAPI's OpenAPI (`npm run gen:api`). TanStack Query for server state.
- Tests next to the level they test: `tests/unit` (no DB), `tests/integration` (Postgres), `tests/benchmarks`.
- Prefer small pure functions with docstrings that cite the plan section they implement (e.g. `"""Plan §5.3 ratable daily."""`).

## Key dates

FYP-I demo **11 Dec 2026** · Mid-Year Defense 18 Dec 2026 · engine/journals/close/reports end Mar 2027 · zero-variance test report end Apr 2027 · final submission **9 Jun 2027** · viva 16 Jun 2027.
