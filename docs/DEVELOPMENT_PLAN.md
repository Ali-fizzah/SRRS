# Development Plan — Subscription-Based Revenue Recognition System

> **Source of truth for building the FYP.** Derived from *Subscription-Based Revenue Recognition System — FYP Proposal (Final)* and the Excel benchmark workbooks (`REVREC_Model_Final.xlsx`, `REVREC_Mock_Data.xlsx`).
> Keep this file at `docs/DEVELOPMENT_PLAN.md`. `CLAUDE.md` at the repo root points here.
> Plan written: 30 Oct 2026 (end of proposal Month 2).

---

## 0. How to use this document

**For the team:** sections 2–11 are the specification. Section 12 is the build plan, broken into tasks with IDs (`P1-T3`), owners and acceptance criteria. Tick tasks off in the GitHub issue that carries the same ID.

**For Claude Code:** work on **one task ID at a time**. Before writing code for a task, read the spec sections the task lists under *Read first*. A task is done only when its acceptance criteria pass and the Definition of Done (§13) holds. If a task needs a decision this plan does not make, stop and ask; do not invent accounting rules.

Example prompts:

```
Read CLAUDE.md and docs/DEVELOPMENT_PLAN.md §12. Implement task P0-T1. Show me the plan before writing files.
Implement P3-T2 (allocation). Read §5.2–5.3 first. Add the unit tests listed in the task, run the benchmark suite, and report any variance.
Review the current branch against §13 Definition of Done and list anything missing.
```

---

## 1. Project summary

A web-based revenue sub-ledger for simple subscription contracts, applying a simplified ASC 606 / IFRS 15 five-step model. Users upload contract and billing data. The system validates it, allocates the transaction price by relative SSP, generates revenue schedules, books balanced journal entries, and closes accounting periods. A built-in MUI reporting suite presents the results. Outputs must match the Excel benchmarks to the cent.

| Item | Value |
|---|---|
| Stack | Next.js + MUI (community) · FastAPI · Python/Pandas/NumPy · PostgreSQL · SQLAlchemy + Alembic · pytest |
| Team | M1 Accounting & benchmarks · M2 Backend & engine · M3 Database, API & security · M4 Frontend & reporting |
| FYP-I end-to-end demo | **11 Dec 2026** (upload → validation → DB → ratable monthly schedule → MUI grid) |
| FYP-I Mid-Year Defense | **18 Dec 2026** |
| Engine, journals, close, reports complete | End of Mar 2027 |
| Signed zero-variance test report | End of Apr 2027 |
| Final submission | **9 Jun 2027** |
| Viva | **16 Jun 2027** |

---

## 2. Decisions locked by this plan

These fill gaps in the proposal or reconcile it with the Excel benchmarks. Items marked **M1 sign-off** must be confirmed by the accounting lead and mirrored in the Excel benchmarks before the related phase starts.

| ID | Decision | Why | Status |
|---|---|---|---|
| D1 | Money is **integer cents** (`int64`) inside the engine, `NUMERIC(18,2)` in PostgreSQL, `Decimal` / string in the API. **Never `float`.** | Exact arithmetic; zero-variance requirement | Locked |
| D2 | Rounding is `ROUND_HALF_UP` to 2 dp. Allocation plug goes to the obligation with the largest SSP (tie → lowest line number). **Ratable daily uses cumulative rounding** (§5.3). Ratable monthly uses equal months with the final month absorbing the difference (proposal §4.3). | Checked against `REVREC_Mock_Data.xlsx`: per-month rounding + last-month plug misses the 0.01 pass rule by up to 0.028; cumulative rounding stays within 0.0092 | **M1 sign-off** |
| D3 | The Excel method `PROPORTIONAL_PERFORMANCE` maps to **`POINT_IN_TIME` with partial deliveries**: tranches are recognised on delivery dates; any undelivered remainder is recognised on the completion date. Adds a 7th input template, *Deliveries*. | Needed for benchmark parity without adding a fourth recognition method | **M1 sign-off** |
| D4 | Lines whose product is **not a separate obligation** (setup fees, $0 bundle header lines) add their price to the transaction price but get no obligation and no SSP share. | Matches proposal §4.3 (setup fees) and the Excel bundle header lines (SSP 0) | Locked |
| D5 | Every schedule line has a **service period** (when revenue is earned) and a **posting period** (when it is booked). Lines whose service period is already closed are booked in the current open period as `REVENUE_CATCH_UP`. | This is the Excel `Revenue_PPA` concept and the proposal's "late change → adjustment in current open period" rule | Locked |
| D6 | Exactly **one OPEN period** at a time (the *current period*). Billing documents dated in a closed period post to the current period. Contract events (cancellation, upgrade) with an effective date **before** the current period are **rejected** at validation. | Keeps modifications prospective; backdated catch-up treatment is out of scope (proposal §2.3) | Locked |
| D7 | Credit notes are **inputs** from the billing system; this system never creates billing documents. A cancellation that leaves deferred revenue without a matching credit note raises a close-checklist warning. | Proposal: billing/AR is out of scope | Locked |
| D8 | Prospective upgrade: SSP basis for an old ratable obligation that continues is `SSP × remaining service days ÷ total service days`; satisfied point-in-time obligations are excluded from reallocation. | Proposal does not define the SSP basis for the remaining term | **M1 sign-off** |
| D9 | Validation is **atomic per contract version**: if any row of a contract (header or line) fails, the whole contract version is quarantined. Other contracts in the file still load. | Allocation needs every line of a contract | Locked |
| D10 | Background jobs use a **PostgreSQL `job_runs` table** + a separate worker process (`SELECT … FOR UPDATE SKIP LOCKED`). No Redis/Celery. | One less service to run and demo | Locked |
| D11 | Auth: FastAPI issues a JWT in an **httpOnly cookie**. Next.js rewrites `/api/*` to FastAPI so browser calls are same-origin. | Simple, secure for a demo | Locked |
| D12 | GL mapping resolves **account roles** (`AR`, `UNBILLED_AR`, `DEFERRED_REVENUE`, `REVENUE`) with precedence *product → product category → default*. Posting rules (§5.7) map each event type to roles. | Implements "product + transaction type → account" | Locked |
| D13 | Roles: `UPLOADER`, `ACCOUNTANT`, `APPROVER`, `ADMIN` (Admin includes Approver). Segregation of duties: the user who generated a journal batch cannot approve it (setting, on by default). | Proposal role list + audit expectations | Locked |
| D14 | Period keys are `YYYYMM` strings (same as the Excel `Actg_Period`). | Easy benchmark comparison | Locked |

---

## 3. Repository layout

```
revrec/
├── CLAUDE.md
├── README.md
├── Makefile                      # dev, test, lint, migrate, seed, bench, load
├── docker-compose.yml            # postgres, api, worker, web
├── .github/workflows/ci.yml
├── docs/
│   ├── DEVELOPMENT_PLAN.md       # this file
│   ├── accounting-rules.md       # Month 1 deliverable (M1)
│   ├── architecture.md           # Month 2 deliverable (M3)
│   ├── erd.md                    # mermaid ERD, generated from models
│   ├── templates.md              # input template spec (mirror of §7)
│   └── user-manual.md            # Month 9
├── backend/
│   ├── pyproject.toml            # ruff, mypy, pytest config
│   ├── alembic/                  # migrations only via Alembic
│   ├── app/
│   │   ├── main.py               # FastAPI app factory
│   │   ├── config.py
│   │   ├── db/                   # session, base, triggers.sql
│   │   ├── models/               # SQLAlchemy 2.0 typed models
│   │   ├── schemas/              # Pydantic v2 request/response models
│   │   ├── api/v1/               # routers: auth, uploads, master, contracts, periods, journals, reports, jobs
│   │   ├── auth/                 # JWT, password hashing, role dependencies
│   │   ├── ingestion/            # templates, parsers, validators, loaders
│   │   ├── engine/               # PURE functions: allocation, methods, events, balances (no DB imports)
│   │   ├── services/             # orchestration: recognition_run, journal_gen, period_close (DB + engine)
│   │   ├── reports/              # SQL/report builders + CSV streaming
│   │   ├── jobs/                 # job queue + worker entrypoint
│   │   └── audit.py
│   └── tests/
│       ├── unit/                 # engine + validators (no DB)
│       ├── integration/          # API + DB (test Postgres)
│       └── benchmarks/           # golden-case runner
├── frontend/
│   ├── package.json
│   ├── next.config.mjs           # rewrites /api → FastAPI
│   └── src/
│       ├── app/                  # App Router pages (§9)
│       ├── components/           # grids, charts, upload, period widgets
│       ├── lib/api/              # typed client generated from OpenAPI
│       └── theme/
├── benchmarks/
│   ├── source/                   # REVREC_Model_Final.xlsx, REVREC_Mock_Data.xlsx, M1 workbooks
│   ├── cases/<CASE_ID>/          # inputs/*.csv, expected/*.csv, case.yaml
│   └── tools/                    # convert_revrec_xlsx.py, compare.py
└── tools/
    ├── generate_dataset.py       # synthetic data at any volume (load tests, demo)
    └── seed.py                   # admin user, chart of accounts, periods
```

---

## 4. Tech stack

| Layer | Choice | Notes |
|---|---|---|
| Front end | Next.js (App Router, TypeScript strict), MUI Core, `@mui/x-data-grid`, `@mui/x-charts`, `@mui/x-date-pickers` (+ dayjs) — **community/MIT only** | TanStack Query for data fetching; typed client from FastAPI OpenAPI via `openapi-typescript` |
| API | FastAPI, Pydantic v2, PyJWT, bcrypt | Routers under `/api/v1` |
| Processing | Python 3.12, Pandas, NumPy, openpyxl | Engine is pure functions over NumPy arrays of cents |
| Database | PostgreSQL 16, SQLAlchemy 2.0, Alembic, psycopg 3 | Bulk inserts via `COPY` |
| Testing | pytest, pytest-postgresql or a CI Postgres service, httpx; ESLint + `tsc` on the front end | Benchmarks run on every PR |
| Quality | ruff (lint + format), mypy (strict on `engine/`), prettier | Enforced in CI |
| Dev env | docker-compose (postgres, api, worker, web); `make dev` | Pin all versions at project start |

**MUI X community limits to design around:** Data Grid pagination is capped at 100 rows per page, one filter at a time, no row grouping/aggregation, no Excel export. Therefore: server-side pagination, sorting and filtering; aggregations computed in SQL; full-dataset CSV export streamed by the API (`?format=csv`), not by the grid.

---

## 5. Accounting engine specification

All of `app/engine/` is **pure**: inputs are dataclasses / NumPy arrays, outputs are dataclasses / arrays. No DB, no I/O, no clock. This is what the benchmarks test.

### 5.1 Glossary

| Term | Meaning |
|---|---|
| Contract | Agreement identified by `contract_code`. Has one or more versions. |
| Contract version | Snapshot created by an event (NEW, RENEWAL, CANCELLATION, UPGRADE). Never edited after creation. |
| Contract line | Product × quantity × price on a version, with a service start/end. |
| Performance obligation (PO) | A contract line whose product is a separate obligation. |
| TP | Transaction price = Σ over all lines of `quantity × unit_price − discount`. |
| Service period | Month in which revenue is earned. |
| Posting period | Month in which the journal is booked (the current open period when posted). |

### 5.2 SSP and allocation

SSP per unit, by the product's SSP source:

| Source | Unit SSP |
|---|---|
| `FIXED` | `ssp_value` |
| `LIST_PRICE` | `list_price` |
| `PCT_OF_LIST` | `list_price × ssp_pct / 100` |

SSP of a PO = unit SSP × quantity. Discounts reduce TP, not SSP. SSP is looked up as of the version's effective date (SSP history is kept, §6).

Allocation:
```
alloc_i  = round_half_up(TP × SSP_i / Σ SSP, 2)
diff     = TP − Σ alloc_i
alloc_k += diff      where k = PO with largest SSP (tie → lowest line_no)
```
Rules: `Σ SSP = 0` → contract rejected (`E014 NO_SEPARATE_OBLIGATION`). Non-separate lines (D4) contribute to TP only.

**Check (proposal §4.4):** TP 12,600; SSP 12,000 + 1,500 = 13,500 → 11,200.00 and 1,400.00.

### 5.3 Recognition methods

All amounts in cents. `A` = allocated amount of the PO.

**RATABLE_DAILY** — service days from `service_start` to `service_end` inclusive, `D` total days. For each period *k* overlapping the service window, `D_k` = cumulative service days through the end of period *k* (capped at `service_end`).
```
cum_k    = round_half_up(A × D_k / D)            # integer: (2·A·D_k + D) // (2·D) for A ≥ 0
amount_k = cum_k − cum_(k−1),   cum_0 = 0
```
The last period's `cum` equals `A` exactly, so no separate plug is needed, and every period is within 0.01 of the unrounded amount. **Write the Excel benchmarks the same way (D2).**

**RATABLE_MONTHLY** — only for service windows that start on the 1st and end on a month end (else `E012 MONTH_ALIGNMENT`). `M` = number of months.
```
monthly = round_half_up(A / M)
periods 1..M−1 → monthly;   period M → A − monthly × (M − 1)
```
**Check (proposal §4.4):** 11,200.00 over 12 → 933.33 × 11, then 933.37.

**POINT_IN_TIME** — recognised in the period containing the `completion_date` (contract line column; defaults to `service_end`).
With deliveries (D3): each delivery recognises `round_half_up(A × units_fraction)` in the delivery month; the remainder `A − Σ tranches` is recognised in the completion month. Σ `units_fraction` > 1 → `E009`. Delivery date after completion date → `E009`.
**Check (proposal §4.4):** training 1,400.00 on 15 Jan.

### 5.4 Service period vs posting period (catch-up)

Schedule lines are generated for every service period of an active PO, status `PENDING`. A recognition run for current period `P` selects all `PENDING` lines of active versions with `service_period ≤ P`, sets `posting_period = P`, and marks lines with `service_period < P` as catch-up. Lines with `service_period > P` stay `PENDING` (future).

Example (`REVREC_Model_Final.xlsx`, Digital line of contract `005984698-INV_106000493`): contract booked in Jul 2025, ratable Jan–Dec 2025. Run for 202507 books Jan–Jun as one `REVENUE_CATCH_UP` amount (Excel `Revenue_PPA` = 5.5044) plus July `REVENUE`.

### 5.5 Contract events

Each event creates a new contract version. Posted schedule lines are never changed; only `PENDING` lines are superseded.

| Event | Rows uploaded | Engine behaviour |
|---|---|---|
| NEW | contract row + all its lines | Allocate, generate schedules from service start. |
| RENEWAL | contract row (new term) + all lines of the new term | New version with its own TP, allocation and schedules. Previous version untouched. |
| CANCELLATION | contract row with `effective_date` = cancellation date; no lines | Ratable POs recognise through the cancellation date (daily: cumulative days to that date; monthly: requires a month-end date). All `PENDING` lines after it are superseded. Unsatisfied point-in-time POs recognise nothing further. Remaining deferred revenue is reversed by an uploaded credit note (D7). |
| UPGRADE (prospective) | contract row with `effective_date` = E + **only the added lines** | `pool = Σ (alloc_i − recognised_i through E−1) over continuing POs + TP of added lines`. Reallocate `pool` by relative SSP (D8 basis) across continuing POs and added POs. New schedules run from E to each PO's end. Old `PENDING` lines from E onward are superseded. |

Validation: for CANCELLATION and UPGRADE, `effective_date` must fall in the current open period or later (D6, `E010`). NEW and RENEWAL may start in earlier periods; revenue already earned is booked as catch-up (§5.4). Contract lines for NEW/RENEWAL/UPGRADE must be in the same upload as their contract row.

### 5.6 Billing, deferred revenue and unbilled receivables

Balances are tracked **per contract**. At any time a contract has either a deferred revenue balance (billed > recognised) or an unbilled receivable balance (recognised > billed), never both.

Order of processing inside a posting period (deterministic): invoices and credit notes by document date then number, then revenue.

| Event | Rule |
|---|---|
| Invoice amount `x` | Cr `UNBILLED_AR` up to its balance, remainder Cr `DEFERRED_REVENUE`; Dr `AR` for `x` |
| Credit note amount `x` | Dr `DEFERRED_REVENUE` for `x`; Cr `AR`. If `x` > deferred balance → `E009` (reversing recognised revenue is out of scope) |
| Revenue recognised `r` | Cr `REVENUE` (by product) for `r`; Dr `DEFERRED_REVENUE` up to its balance, remainder Dr `UNBILLED_AR` |

Deferred revenue rollforward per period: `opening + billings − credit notes − recognised (from deferred) = closing`. Two independent checks at close: (a) rollforward from the sub-ledger equals the GL balance of the deferred revenue account(s); (b) Σ debits = Σ credits in the batch.

### 5.7 Journal generation and lifecycle

Posting rules (event → roles). Accounts come from `gl_mappings` (D12).

| Entry type | Debit role | Credit role |
|---|---|---|
| `INVOICE` (billed in advance) | AR | DEFERRED_REVENUE |
| `INVOICE` (after recognition) | AR | UNBILLED_AR |
| `REVENUE` / `REVENUE_CATCH_UP` (already billed) | DEFERRED_REVENUE | REVENUE |
| `REVENUE` / `REVENUE_CATCH_UP` (not yet billed) | UNBILLED_AR | REVENUE |
| `CREDIT_NOTE` (unrecognised portion) | DEFERRED_REVENUE | AR |
| `REVERSAL` | mirror of the reversed entry | |

Grain: one entry per invoice, per credit note, and per contract × entry type × posting period for revenue (one credit line per PO's revenue account). Every entry carries `contract_id`, `contract_version_id`, source document / schedule line ids and the source upload + row.

Lifecycle: **DRAFT → APPROVED → POSTED**. A DRAFT batch can be regenerated (deleted and rebuilt; linked schedule lines return to `PENDING`). An APPROVED batch can be sent back to DRAFT by an Approver. POSTED is read-only (enforced in the DB, §6.3). Corrections are new `REVERSAL` / `ADJUSTMENT` entries in the current open period.

Default chart of accounts (seeded, editable): `1100 Accounts Receivable`, `1150 Unbilled Receivable`, `2400 Deferred Revenue`, `4100 Subscription Revenue`, `4200 Print / Hardware Revenue`, `4300 Professional Services Revenue`.

### 5.8 Period close

States: **OPEN → CLOSING → CLOSED**. One OPEN period at a time (D6).

Checklist (computed by the API; each item has status `pass` / `warn` / `fail`):
1. All uploads in this period are in a final state (`ACCEPTED`, `PARTIAL`, `REJECTED`) — none `RECEIVED`/`VALIDATING`.
2. A recognition run finished after the latest accepted upload.
3. A journal batch exists for the period and debits = credits.
4. Deferred revenue rollforward ties to the GL (both checks in §5.6).
5. Warnings: cancelled contracts with residual deferred and no credit note (D7).
6. The batch is POSTED.

`start-close` (Accountant) moves OPEN → CLOSING and blocks new uploads. `close` (Approver) requires items 1–4 and 6 to pass; it sets CLOSED, opens the next period, and writes the audit log. `reopen` (Admin only, reason required) is allowed only for the latest CLOSED period and only if the following period has no POSTED batch; it is audit-logged.

### 5.9 MRR / ARR (non-GAAP)

MRR for month *m* = Σ `net_price / term_months` over lines of ratable products whose service window covers the month end (`term_months` = service window length in months, rounded to the nearest whole month). ARR = MRR × 12. Always labelled separately from GAAP revenue.

---

## 6. Database schema

Owner: M3. All tables have `id BIGSERIAL PK`, `created_at`, and (where imported) `source_upload_id FK → upload_files`, `source_row INT`, `source_payload JSONB` — written below as **`src`**.

### 6.1 Tables

**Master data**
```
customers(customer_code UQ, name, country CHAR(2), src)
products(product_code UQ, name, category NULL, list_price NUMERIC(18,2),
         recognition_method ENUM(RATABLE_DAILY, RATABLE_MONTHLY, POINT_IN_TIME),
         is_separate_obligation BOOL, revenue_account_id FK, src)
ssp_rules(product_id FK, ssp_source ENUM(FIXED, LIST_PRICE, PCT_OF_LIST),
          ssp_value NUMERIC(18,2) NULL, ssp_pct NUMERIC(7,4) NULL,
          valid_from DATE, valid_to DATE NULL, src)          -- history, never overwritten
gl_accounts(account_code UQ, name, type ENUM(ASSET, LIABILITY, REVENUE), is_active)
gl_mappings(account_role ENUM(AR, UNBILLED_AR, DEFERRED_REVENUE, REVENUE),
            product_id NULL, product_category NULL, account_id FK)   -- precedence product > category > default (both NULL)
```

**Contracts**
```
contracts(contract_code UQ, customer_id FK, status ENUM(ACTIVE, CANCELLED, EXPIRED), current_version_no)
contract_versions(contract_id FK, version_no, event_type ENUM(NEW, RENEWAL, CANCELLATION, UPGRADE),
                  effective_date, start_date, end_date, transaction_price NUMERIC(18,2),
                  booked_period CHAR(6), src,  UQ(contract_id, version_no))
contract_lines(contract_version_id FK, line_no, product_id FK, quantity NUMERIC(12,4),
               unit_price, discount, net_price, service_start, service_end, completion_date NULL, src)
performance_obligations(contract_version_id FK, contract_line_id FK, product_id FK, method,
                        ssp_amount, allocated_amount, service_start, service_end, completion_date,
                        carried_from_po_id NULL, status ENUM(ACTIVE, SUPERSEDED, SATISFIED))
deliveries(delivery_code UQ, contract_line_id FK, delivery_date, units_fraction NUMERIC(9,6), src)
```

**Billing**
```
invoices(invoice_number UQ, contract_id FK, invoice_date, total_amount, src)
invoice_lines(invoice_id FK, contract_line_id FK NULL, line_no, amount)
credit_notes(credit_note_number UQ, invoice_id FK, credit_date, amount, reason, src)
```

**Revenue**
```
revenue_schedules(performance_obligation_id FK, contract_version_id FK,
                  status ENUM(ACTIVE, SUPERSEDED), generated_by_job_id FK)
schedule_lines(schedule_id FK, service_period CHAR(6), amount NUMERIC(18,2),
               status ENUM(PENDING, POSTED, SUPERSEDED), posting_period CHAR(6) NULL,
               is_catch_up BOOL, journal_line_id FK NULL)
```

**Ledger**
```
accounting_periods(period_key CHAR(6) UQ, start_date, end_date,
                   status ENUM(OPEN, CLOSING, CLOSED), closed_by, closed_at)
journal_batches(period_id FK, batch_no, status ENUM(DRAFT, APPROVED, POSTED),
                generated_by, approved_by, approved_at, posted_by, posted_at, total_debit, total_credit)
journal_entries(batch_id FK, entry_type ENUM(INVOICE, CREDIT_NOTE, REVENUE, REVENUE_CATCH_UP, REVERSAL, ADJUSTMENT),
                entry_date, contract_id, contract_version_id, source_type, source_id,
                reverses_entry_id NULL, description)
journal_lines(entry_id FK, account_id FK, debit NUMERIC(18,2), credit NUMERIC(18,2),
              product_id NULL, performance_obligation_id NULL,
              CHECK (debit >= 0 AND credit >= 0 AND (debit = 0 OR credit = 0)))
```

**Control**
```
upload_files(template ENUM, original_filename, sha256, stored_path, uploaded_by, period_key,
             status ENUM(RECEIVED, VALIDATING, ACCEPTED, PARTIAL, REJECTED),
             total_rows, accepted_rows, rejected_rows)
validation_errors(upload_file_id FK, row_number, column_name, error_code, message, raw_value)
job_runs(job_type ENUM(INGEST, RECOGNITION, JOURNALS, EXPORT), status ENUM(QUEUED, RUNNING, DONE, FAILED),
         params JSONB, progress INT, result JSONB, error TEXT, created_by, started_at, finished_at)
audit_log(at, user_id, action, entity_type, entity_id, before JSONB, after JSONB, reason)
users(email UQ, full_name, password_hash, is_active)
roles(name UQ)          user_roles(user_id, role_id)
```

### 6.2 Indexes (minimum)

`schedule_lines(status, service_period)`, `schedule_lines(posting_period)`, `schedule_lines(schedule_id)`, `journal_lines(entry_id)`, `journal_lines(account_id)`, `journal_entries(batch_id)`, `journal_entries(contract_id)`, `contract_versions(contract_id, version_no)`, `validation_errors(upload_file_id)`, all FKs. Revisit in Phase 7 with `EXPLAIN ANALYZE`.

### 6.3 Database-enforced rules (triggers in a migration)

- No UPDATE/DELETE on `journal_entries` / `journal_lines` whose batch is POSTED.
- A batch can move to POSTED only if Σ debit = Σ credit.
- No INSERT into `journal_batches` for a period that is CLOSED (OPEN and CLOSING are allowed — journals are generated during close).
- No UPDATE/DELETE of `schedule_lines` with status POSTED.
- No UPDATE/DELETE on `contract_versions`, `audit_log`.

---

## 7. Input templates and validation

Owner: M1 defines, M2 implements. Headers are **exact, snake_case**, in this column order. Files whose headers don't match are rejected whole (`E011`). `.csv` (UTF-8) and `.xlsx` (first sheet) both accepted. Dates: ISO `YYYY-MM-DD` or native Excel dates.

> Ingestion gotcha: read every column as **string** (`dtype=str`), then parse. IDs such as `005984698-INV_106000493` lose leading zeros otherwise.

| Template | Columns (required unless marked *opt*) |
|---|---|
| customers | `customer_id, name, country` |
| products | `product_id, name, category`*opt*`, list_price, ssp_source, ssp_value`*opt*`, ssp_pct`*opt*`, recognition_method, separate_obligation (Y/N), revenue_gl_account, ssp_valid_from`*opt* |
| contracts | `contract_id, customer_id, start_date, end_date, event_type, effective_date` |
| contract_lines | `contract_id, line_no, product_id, quantity, unit_price, discount`*opt, default 0*`, service_start, service_end, completion_date`*opt* |
| invoices | `invoice_number, contract_id, invoice_date, line_no, amount` (one row per invoice line) |
| credit_notes | `credit_note_number, invoice_number, credit_date, amount, reason` |
| deliveries (D3) | `delivery_id, contract_id, line_no, delivery_date, units_fraction` |

Multi-file uploads are processed in dependency order: customers → products → contracts → contract_lines → invoices → credit_notes → deliveries. Downloadable blank templates + one example row each at `GET /api/v1/templates/{name}`.

### 7.1 Error codes

| Code | Meaning |
|---|---|
| E001 | Missing required value |
| E002 | Wrong type (number expected, etc.) |
| E003 | Invalid date |
| E004 | Unknown reference (customer, product, contract, invoice, account) |
| E005 | Duplicate key within the file |
| E006 | Duplicate key already in the database |
| E007 | Date range invalid (end before start, line outside contract term) |
| E008 | Negative amount / quantity where not allowed |
| E009 | Business rule violation (see message) |
| E010 | CANCELLATION / UPGRADE effective date in a closed period (D6) |
| E011 | File-level: headers do not match the template (whole file rejected) |
| E012 | RATABLE_MONTHLY window not aligned to whole months |
| E013 | Quarantined because another row of the same contract version failed (D9) |
| E014 | Contract has no separate performance obligation |

Every error row stores upload id, row number, column, code, message and raw value; the log is downloadable as CSV.

---

## 8. API

Prefix `/api/v1`. All list endpoints accept `page`, `page_size` (≤ 100), `sort`, and the filters `period_from`, `period_to`, `customer`, `contract`, `product`; and `format=csv` to stream the full filtered result.

| Area | Endpoints | Min. role |
|---|---|---|
| Auth | `POST /auth/login`, `POST /auth/logout`, `GET /auth/me` | — |
| Users | `GET/POST /users`, `PATCH /users/{id}` | ADMIN |
| Templates | `GET /templates`, `GET /templates/{name}` | UPLOADER |
| Uploads | `POST /uploads` (multipart, one or more files → job), `GET /uploads`, `GET /uploads/{id}`, `GET /uploads/{id}/errors`, `GET /uploads/{id}/file` | UPLOADER |
| Master data | `GET /customers`, `GET/POST/PATCH /products`, `GET /products/{id}/ssp-history`, `GET/POST/PATCH /gl-accounts`, `GET/POST/PATCH /gl-mappings` | read: UPLOADER · write: ACCOUNTANT |
| Contracts | `GET /contracts`, `GET /contracts/{id}`, `GET /contracts/{id}/versions/{n}`, `GET /contracts/{id}/schedule`, `GET /contracts/{id}/billing`, `GET /contracts/{id}/journal-lines`, `GET /contracts/{id}/source-rows` | UPLOADER |
| Engine | `POST /periods/{key}/recognition-run`, `POST /periods/{key}/journals/generate` → job | ACCOUNTANT |
| Jobs | `GET /jobs/{id}` | any |
| Journals | `GET /journal-batches`, `GET /journal-batches/{id}`, `POST …/{id}/approve`, `POST …/{id}/send-back`, `POST …/{id}/post`, `POST /journal-entries/{id}/reverse` | view: ACCOUNTANT · approve/post: APPROVER |
| Periods | `GET /periods`, `GET /periods/{key}/checklist`, `POST /periods/{key}/start-close` (ACCOUNTANT), `POST /periods/{key}/close` (APPROVER), `POST /periods/{key}/reopen` (ADMIN, `reason` required) | |
| Reports | `GET /reports/revenue-schedule`, `/deferred-rollforward`, `/recognized-vs-deferred`, `/journal-register`, `/gl-summary`, `/mrr-arr`, `/close-status`, `/validation-log` | UPLOADER (validation log) · ACCOUNTANT (others) |

Every state-changing endpoint writes `audit_log`. Errors use one JSON shape: `{ "error": { "code", "message", "details" } }`.

---

## 9. Front end

Owner: M4. Next.js App Router, MUI theme, responsive down to tablet (≥ 768 px). Server-side pagination on every grid.

| Route | Content | MUI |
|---|---|---|
| `/login` | Sign in | TextField, Button |
| `/` | Dashboard: current period card, checklist progress, recognised vs deferred mini-chart, recent uploads | Card, Chip, LineChart |
| `/uploads` | Drag-and-drop upload (multi-file), template downloads, upload history with status chips | DataGrid |
| `/uploads/[id]` | Validation log for one upload, CSV download | DataGrid |
| `/master-data/{customers,products,accounts,mappings}` | View/edit master data; SSP history drawer | DataGrid, Drawer |
| `/contracts` | Contract list with filters | DataGrid |
| `/contracts/[id]` | Versions timeline, lines, POs + allocation, schedule, billing, journal lines, **source rows** (drill-down end point) | Tabs, Timeline, DataGrid |
| `/journals` | Batches by period and status; approve / send back / post | DataGrid, Dialog |
| `/journals/[batchId]` | Entries + lines, balance check, reverse action | DataGrid |
| `/periods` | Period list; close workflow with live checklist; reopen (Admin) | Card, Stepper, Chip |
| `/reports/revenue-schedule` | Recognised per contract line per month | DataGrid |
| `/reports/deferred-rollforward` | Opening, billings, credit notes, recognised, closing | DataGrid + BarChart |
| `/reports/trend` | Monthly recognised revenue and deferred balance | LineChart |
| `/reports/journal-register` | All entries by period, status, account | DataGrid |
| `/reports/gl-summary` | Debit, credit, net per account per period | DataGrid |
| `/reports/mrr-arr` | MRR and ARR (labelled non-GAAP) | LineChart |
| `/reports/close-status` | State of each period + checklist | Card, Chip |

**Drill-down (audit trail):** every summary figure links to a filtered detail report → contract page → *Source rows* tab, which shows the stored `source_payload`, file name and row number.

Every report has a filter bar (period range picker, customer, contract, product), **Export CSV** (calls `?format=csv`) and **Print** (print stylesheet).

---

## 10. Background jobs

`job_runs` table + `python -m app.jobs.worker`. API endpoints that start long work insert a `QUEUED` job and return `{ job_id }`; the worker claims jobs with `FOR UPDATE SKIP LOCKED`, updates `progress`, and stores `result` or `error`. The UI polls `GET /jobs/{id}` every 1–2 s. Jobs: `INGEST`, `RECOGNITION`, `JOURNALS`, `EXPORT`. Each job runs in one DB transaction per contract chunk (e.g. 2,000 contracts) so a failure doesn't leave half-written schedules.

---

## 11. Testing and benchmarks

### 11.1 Test levels

| Level | Where | Runs |
|---|---|---|
| Unit — engine math, validators | `backend/tests/unit` | every PR |
| Integration — API + DB + triggers + roles | `backend/tests/integration` (Postgres service in CI) | every PR |
| Golden benchmarks | `backend/tests/benchmarks` over `benchmarks/cases/*` | every PR |
| Front end — lint, typecheck, build | `frontend` | every PR |
| Load test | `make load N=50000` | Phase 7, manually |

**Pass rule:** every schedule amount and every journal amount within **0.01** of the expected value, and every PO's schedule total exactly equal to its allocation. **Never edit an `expected/` file to make a test pass** — a variance is either a bug or a benchmark error that M1 must confirm in writing (commit message + note in `case.yaml`).

### 11.2 Benchmark case format

```
benchmarks/cases/B01_worked_example/
├── case.yaml          # description, periods to replay, open period at start, tolerance, owner
├── inputs/            # system templates (§7), one folder per replay month if needed: inputs/202501/*.csv
└── expected/
    ├── allocation.csv   # contract_id, line_no, allocated_amount
    ├── schedule.csv     # contract_id, line_no, service_period, amount
    ├── postings.csv     # posting_period, contract_id, line_no, entry_type, amount   (revenue credits, AR debits)
    └── balances.csv     # period, contract_id, deferred, unbilled                     (optional)
```

The runner **replays** a case month by month exactly as a user would: open period → upload that month's files → recognition run → generate journals → approve → post → close → next month. Then it compares DB results to `expected/`. This tests ingestion, engine, journals and close together.

### 11.3 Golden cases

Owner M1 (expected values in Excel), M2 wires them into the runner.

| ID | Level | Case | Key expected values |
|---|---|---|---|
| U01 | Unit | 12-month subscription, ratable monthly, 1 Jan–31 Dec, 1,200 | 100.00 × 12 |
| U02 | Unit | Mid-month start, ratable daily (e.g. 15 Mar–14 Mar) | cumulative rounding (§5.3) |
| U03 | Unit | One point-in-time item | full amount in completion month |
| B01 | Bundle | **Proposal §4.4 worked example** | 11,200.00 / 1,400.00; 933.33 × 11 + 933.37; 1,400.00 on 15 Jan; end Jan recognised 2,333.33, deferred 10,266.67 |
| B02 | Bundle | Three-line bundle with discount | allocation + plug to largest SSP |
| B03 | Bundle | Setup fee (non-separate) + subscription | setup fee spread via TP (D4) |
| E01 | Events | Renewal | new version, old untouched |
| E02 | Events | Cancellation in month 5 + credit note | recognition stops; deferred reversed |
| E03 | Events | Upgrade in month 7 | prospective reallocation (D8) |
| J01 | Journals | Invoice in advance + monthly recognition | AR/Deferred/Revenue |
| J02 | Journals | Credit note on unrecognised portion | Dr Deferred / Cr AR |
| J03 | Journals | Recognition before invoice, then invoice | Unbilled AR then reclass |
| C01 | Close | Close Jan; try to change Jan (rejected); late Jan invoice → posts in Feb | DB triggers + catch-up |
| X01 | Excel | `REVREC_Model_Final.xlsx` — 3 contracts, 9 lines | from workbook (§11.4) |
| X02 | Excel | `REVREC_Mock_Data.xlsx` — 20 contracts, 60 lines, 22 deliveries | from workbook (§11.4) |
| L01 | Load | Generated 50,000 contract lines | performance only (< 5 min) |

### 11.4 Converting the Excel workbooks (task P0-T5)

`benchmarks/tools/convert_revrec_xlsx.py <workbook.xlsx> <case_dir>` produces `inputs/` and `expected/` from the workbook's **calculated values** (open with `data_only=True`; recalculate first if values are missing).

| Workbook sheet / column | System template / field |
|---|---|
| `Input_SaleOrderDetails.Instrumentid` | `contracts.contract_id` (string, keep leading zeros) |
| `Subscription_Id` | `customers.customer_id` as `CUST-<Subscription_Id>`; name synthesised |
| `subInstrumentid` | `contract_lines.line_no` |
| `Service_start_date` / `Service_end_date` | `contract_lines.service_start` / `service_end`; contract `start_date`/`end_date` = min/max over lines |
| `Sale_price`, `Quantity` | `unit_price`, `quantity` (discount 0) |
| `PostingDate` | the **replay month** in which the contract, its invoice and catch-up are processed; `event_type = NEW`, `effective_date` = contract start |
| `Invoice_number`, `PostingDate`, `Bookings_amount` | `invoices` row per line (`invoice_date` = PostingDate) |
| `Input_SSPRule.Product_Code` | `products.product_id`; `list_price` = SSP amount; `ssp_source = FIXED`, `ssp_value = Amount` |
| `Amount = 0` and code has no `_Print`/`_Digital` suffix (bundle header) | `separate_obligation = N` (D4) |
| `Recognition Method = RATABLE` | `RATABLE_DAILY` |
| `= POINT_IN_TIME` | `POINT_IN_TIME`, `completion_date` = service start (Excel recognises in the start month) |
| `= PROPORTIONAL_PERFORMANCE` (separate obligations) | `POINT_IN_TIME`, `completion_date` = service end, plus deliveries (D3) |
| `inp_ProfessionalServiceDelivery` | `deliveries` (`delivery_date` = EffectiveDate; uploaded in the replay month of its PostingDate) |
| `CALCULATION.I` (Allocated_revenue) | `expected/allocation.csv` |
| `CALCULATION` period columns R… (service period from row 3 `Actg_Period`) | `expected/schedule.csv` (non-zero cells only) |
| `Transaction` rows `Revenue_PPA` + `Revenue` | `expected/postings.csv` — sum per (posting period, contract, line), sign flipped to a positive revenue credit |
| `Transaction` rows `New_Billing` | `expected/postings.csv` entry_type `INVOICE` (AR debit) |

Notes for parity:
- The Excel `RATABLE` formula is unrounded per day; the system uses cumulative rounding (D2) → differences ≤ 0.0092 on the mock data, inside the 0.01 rule.
- Excel `Revenue_PPA` is rounded to 4 dp; compare at 0.01.
- Replay periods run from the earliest PostingDate to the latest service end (Jan 2025 → Dec 2027 for X02) so every remainder posts.
- The Excel ratable formula assumes every contract starts in period 1; the system has no such limit, so also generate (with `tools/generate_dataset.py`) cases with staggered starts and check them against M1's hand calculations.

---

## 12. Build plan

Owners: **M1** accounting/benchmarks · **M2** ingestion/engine · **M3** DB/API/security · **M4** front end. Every task = one GitHub issue + one branch `feat/<task-id>-<slug>` + one PR reviewed by a second member.

### Phase 0 — Bootstrap (31 Oct – 8 Nov 2026)

| ID | Owner | Task | Read first | Acceptance criteria |
|---|---|---|---|---|
| P0-T1 | M3 | Monorepo skeleton per §3; docker-compose (postgres, api, worker, web); Makefile targets `dev test lint migrate seed bench` | §3, §4 | `make dev` brings up all four services; `GET /api/v1/health` returns 200 through the Next.js rewrite |
| P0-T2 | M3 | CI: ruff, mypy, pytest with Postgres service, frontend lint/typecheck/build | §4, §11.1 | CI green on an empty test; fails on a lint error |
| P0-T3 | M1 | Move Month 1 rules into `docs/accounting-rules.md`; sign off D2, D3, D8 | §2, §5 | Doc merged; decisions table updated to "Locked" |
| P0-T4 | M1 | Put both workbooks in `benchmarks/source/`; create empty case folders for §11.3 | §11 | Folders + `case.yaml` stubs exist |
| P0-T5 | M2 | `convert_revrec_xlsx.py` (§11.4) for X01 and X02 | §7, §11.4 | Generates `inputs/` and `expected/`; row counts: X02 = 60 lines, 22 deliveries, 20 invoices |
| P0-T6 | M4 | Next.js app, MUI theme, layout shell with nav, login page stub | §9 | Pages render; nav shows all routes as placeholders |

### Phase 1 — Schema, master data, ingestion & validation (9 Nov – 30 Nov 2026) · proposal Month 2–3

| ID | Owner | Task | Read first | Acceptance criteria |
|---|---|---|---|---|
| P1-T1 | M3 | SQLAlchemy models + first Alembic migration for **all** §6.1 tables; `docs/erd.md` (mermaid) | §6 | `alembic upgrade head` on empty DB; `downgrade base` works |
| P1-T2 | M3 | Triggers §6.3 in a migration + integration tests that each blocked operation raises | §6.3 | Tests prove posted/closed data cannot change |
| P1-T3 | M3 | Auth: users, roles, JWT cookie, `require_role()` dependency; seed admin | §8, D11, D13 | Role matrix tests pass for every router stub |
| P1-T4 | M3 | `tools/seed.py`: chart of accounts, default GL mappings, periods 2025-01 → 2028-12, current period | §5.7, §5.8 | `make seed` idempotent |
| P1-T5 | M2 | Template registry (headers, types, required, order) + blank template download | §7 | `GET /templates/{name}` returns CSV with headers + example row |
| P1-T6 | M2 | Parser: csv/xlsx → DataFrame (all str), header check (E011), date/number parsing | §7 | Unit tests incl. leading zeros, Excel serial dates, BOM, blank trailing rows |
| P1-T7 | M2 | Validators E001–E010, E012–E014, contract-level quarantine (D9) | §7.1 | One unit test per error code; quarantine test |
| P1-T8 | M2 | Loader: valid rows → DB with `src` columns via COPY; errors → `validation_errors`; upload status | §6, §10 | Integration test: mixed file → correct accepted/rejected counts |
| P1-T9 | M3 | Job queue + worker; `POST /uploads` creates INGEST job | §10 | Upload of X02 inputs completes via worker; progress visible |
| P1-T10 | M4 | `/uploads` page (multi-file, history, status chips) and `/uploads/[id]` error log + CSV | §9 | Upload a bad file in the UI → see error rows → download CSV |
| P1-T11 | M4 | Master data pages (read-only grids for now) | §9 | Grids paginate server-side |

**Milestone (30 Nov):** raw files validated end to end with downloadable error logs (proposal Month 3).

### Phase 2 — FYP-I vertical slice (1 Dec – 11 Dec 2026) · **demo 11 Dec, defense 18 Dec**

Build the slice on the real engine modules; nothing here is throwaway.

| ID | Owner | Task | Read first | Acceptance criteria |
|---|---|---|---|---|
| P2-T1 | M2 | `engine/methods.py`: `ratable_monthly()` in integer cents + unit tests (U01, B01 subscription line) | §5.3 | 933.33 × 11 + 933.37 for 11,200 / 12 |
| P2-T2 | M2 | `engine/allocation.py` for single-PO contracts (full version in P3) | §5.2 | U01 allocation = TP |
| P2-T3 | M2 | `services/recognition_run.py`: generate + persist `revenue_schedules` / `schedule_lines` for accepted contracts | §5.4 | Integration test: upload U01 → 12 schedule lines |
| P2-T4 | M3 | `GET /contracts`, `GET /contracts/{id}/schedule`, `POST /periods/{key}/recognition-run` | §8 | API tests |
| P2-T5 | M4 | `/contracts` and `/contracts/[id]` schedule tab (DataGrid) | §9 | Shows the 12 lines with totals |
| P2-T6 | M1+M4 | Demo dataset (3–5 subscriptions incl. one bad file) + scripted demo walkthrough in `docs/demo-fyp1.md`; screenshots for the report | — | Full run-through in < 5 min, rehearsed twice |

**Milestone (11 Dec):** upload → validation → database → ratable monthly schedule → MUI grid.

### Phase 3 — Recognition engine (4 Jan – 31 Jan 2027) · proposal Month 5

| ID | Owner | Task | Read first | Acceptance criteria |
|---|---|---|---|---|
| P3-T1 | M2 | SSP resolution (3 sources, SSP history by effective date) | §5.2 | Unit tests per source |
| P3-T2 | M2 | Full allocation with non-separate lines (D4) and plug rule | §5.2 | B01, B02, B03 allocation pass |
| P3-T3 | M2 | `ratable_daily()` cumulative rounding; `point_in_time()` with deliveries | §5.3, D3 | U02, U03; property test: Σ schedule = allocation for random inputs |
| P3-T4 | M2 | Catch-up / posting-period assignment in recognition run | §5.4 | X01 schedule matches; Excel `Revenue_PPA` reproduced |
| P3-T5 | M2 | Billing tracking: invoices/credit notes vs recognition → per-contract deferred / unbilled balances | §5.6 | B01: end Jan deferred 10,266.67 |
| P3-T6 | M3 | Deliveries template wired end to end; contract detail endpoints (versions, POs, billing) | §7, §8 | API tests |
| P3-T7 | M2 | Benchmark runner (replay, compare, variance report as CSV) | §11.2 | `make bench` runs all cases; prints per-case pass/fail and max variance |
| P3-T8 | M4 | Contract detail tabs: lines, POs + allocation, billing | §9 | Matches API |

**Milestone (31 Jan):** all Unit and Bundle cases + X01 + X02 **schedules** pass.

### Phase 4 — Contract events & journals (1 Feb – 28 Feb 2027) · proposal Month 6

| ID | Owner | Task | Read first | Acceptance criteria |
|---|---|---|---|---|
| P4-T1 | M2 | Versioning service: RENEWAL, CANCELLATION, UPGRADE; supersede PENDING lines only | §5.5 | E01, E02, E03 schedules pass; posted lines untouched (test) |
| P4-T2 | M2 | GL mapping resolver (product → category → default) with missing-mapping error | D12 | Unit tests |
| P4-T3 | M2 | Journal generation for a period (invoice, credit note, revenue, catch-up) with deferred/unbilled split | §5.6, §5.7 | J01–J03 pass; every batch balanced |
| P4-T4 | M3 | Batch lifecycle endpoints, SoD rule, reversal endpoint; audit log on each action | §5.7, §8 | Integration tests incl. "generator cannot approve" |
| P4-T5 | M4 | `/journals` and `/journals/[batchId]` with approve / send back / post / reverse | §9 | Full lifecycle through the UI |
| P4-T6 | M1 | Expected postings for E01–E03, J01–J03 | §11.3 | Files committed and reviewed |

**Milestone (28 Feb):** balanced journal batches for every benchmark case; X01 and X02 postings pass.

### Phase 5 — Period close & reporting suite (1 Mar – 31 Mar 2027) · proposal Month 7

| ID | Owner | Task | Read first | Acceptance criteria |
|---|---|---|---|---|
| P5-T1 | M3 | Period state machine, checklist endpoint, start-close / close / reopen with rules | §5.8 | C01 passes; reopen rules tested |
| P5-T2 | M2 | Rollforward computation (sub-ledger) + GL tie-out check | §5.6 | Ties for every replayed month of X02 |
| P5-T3 | M3 | Report endpoints (8) with filters, server pagination, `format=csv` streaming | §8 | CSV of X02 revenue schedule has every row |
| P5-T4 | M4 | `/periods` close workflow with live checklist | §9 | Close a month entirely in the UI |
| P5-T5 | M4 | Report pages + charts + CSV export + print stylesheet | §9 | All 8 reports render for X02 data |
| P5-T6 | M4 | Drill-down: report figure → contract → source row | §9 | Works from 3 different reports |
| P5-T7 | M2 | MRR/ARR computation | §5.9 | Unit tests |

**Milestone (31 Mar):** a full month can be uploaded, recognised, journaled, reviewed and closed through the UI.

### Phase 6 — Testing with realistic data (1 Apr – 30 Apr 2027) · proposal Month 8

| ID | Owner | Task | Acceptance criteria |
|---|---|---|---|
| P6-T1 | M2 | `tools/generate_dataset.py`: any volume, staggered starts, bundles, deliveries, events, invoices, credit notes; seeded RNG | Produces valid templates that pass ingestion |
| P6-T2 | M1 | Advisor review sessions on realistic datasets; record findings as issues | Notes in `docs/validation-log.md` |
| P6-T3 | All | Run order: single contracts → bundles → events → close; fix variances | All golden cases pass at 0.01 |
| P6-T4 | M1 | Variance report generator → signed test report (PDF from markdown) | Report shows zero variance per case |
| P6-T5 | M3 | Security pass: role tests on every endpoint, password policy, rate-limit login | Test matrix 100 % |

**Milestone (30 Apr):** signed zero-variance test report.

### Phase 7 — Performance & hardening (1 May – 31 May 2027) · proposal Month 9

| ID | Owner | Task | Acceptance criteria |
|---|---|---|---|
| P7-T1 | M2 | Vectorise schedule generation (NumPy over all POs at once); chunked transactions | Profiling shows engine < 60 s for 50k lines |
| P7-T2 | M3 | `COPY` for schedule lines and journal lines; index review with `EXPLAIN ANALYZE` | Ingest + recognition + journals for 50k lines **< 5 min** (L01) |
| P7-T3 | M4 | UI polish: loading/empty/error states, tablet layout, accessibility labels | Lighthouse accessibility ≥ 90 |
| P7-T4 | M3 | `docs/user-manual.md` with screenshots; `README` install steps tested on a clean machine | A non-member installs and runs the demo from the README |
| P7-T5 | All | Feature freeze 25 May; bug-fix only after | Tag `v0.9.0` |

### Phase 8 — Release (1 Jun – 9 Jun 2027) · proposal Month 10

| ID | Owner | Task | Acceptance criteria |
|---|---|---|---|
| P8-T1 | M3 | Tag `v1.0.0`; archive schema (`pg_dump --schema-only`) and ERD | Release on GitHub |
| P8-T2 | All | Demo script for viva + dry runs; seed a clean demo DB | Two full dry runs |
| P8-T3 | M1 | Final thesis implementation/testing chapters reference this repo's tags | Submitted **9 Jun** |

---

## 13. Definition of Done (every PR)

- [ ] Task ID in branch name, PR title and linked issue.
- [ ] Acceptance criteria in §12 met and demonstrated in the PR description.
- [ ] Unit tests for new engine/validator logic; integration test for new endpoints.
- [ ] `make lint test bench` green locally and in CI; no benchmark `expected/` file changed without M1 approval noted.
- [ ] No `float` in money paths; no raw SQL string formatting with user input.
- [ ] Schema changes only through a new Alembic migration (never edit an applied migration).
- [ ] New endpoints enforce roles and write `audit_log` for state changes.
- [ ] Docs updated if behaviour or a decision changed (`accounting-rules.md`, §2 here).
- [ ] Reviewed and approved by a second member.

---

## 14. Implementation risks

| Risk | Mitigation |
|---|---|
| Rounding drift vs Excel | D2 locked early; benchmarks use the same rule; property tests on Σ schedule = allocation |
| Event logic touches posted data | DB triggers (§6.3) + tests that try it |
| Ingestion of real-world files (leading zeros, Excel dates, stray rows) | Read as strings; parser unit tests with ugly fixtures |
| 50k-line target missed | Vectorised engine + COPY designed in from Phase 3, measured in Phase 7 |
| MUI community grid limits | Server-side pagination/filter/CSV from day one |
| FYP-I slice becomes throwaway | Phase 2 uses the real engine and schema |
| One member blocked | PR review by a second member; every task has a written spec here |

---

## 15. Out of scope — do not build

Variable consideration and its constraint · residual or range-based SSP · contract combination · cumulative catch-up or retrospective modifications · backdated events into closed periods · financing components, principal vs agent, contract costs (ASC 340-40) · multi-currency, FX revaluation, multi-entity · cash application and collections · creating invoices or credit notes. New ideas go to `docs/future-work.md`.
