# Revenue Recognition System

Web-based revenue sub-ledger for subscription contracts (simplified ASC 606 / IFRS 15).
Specification and task list: [docs/DEVELOPMENT_PLAN.md](docs/DEVELOPMENT_PLAN.md).

| Service | Tech | URL |
|---|---|---|
| web | Next.js + MUI | http://localhost:3000 |
| api | FastAPI | http://localhost:8000/api/v1 (docs at `/docs`) |
| worker | Python job worker | — |
| postgres | PostgreSQL 16 | localhost:5432 |

The browser only talks to `web`; Next.js forwards `/api/*` to `api`.

## Run with Docker (recommended)

Requires Docker Desktop and `make`.

```bash
cp .env.example .env
make dev          # builds and starts postgres, api, worker, web
```

Open http://localhost:3000. The home page shows `API health: ok` when the rewrite reaches FastAPI.

## Run without Docker

Requires Python 3.12, Node.js 20+ and `make`. PostgreSQL 16 is needed from Phase 1 on.

```bash
# backend (Windows: py -3.12 -m venv .venv  and  .venv\Scripts\activate)
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --reload --port 8000

# frontend (second terminal)
cd frontend
npm install
npm run dev
```

With the backend virtualenv activated, the Makefile targets run locally with `LOCAL=1`:

```bash
make test LOCAL=1
make lint LOCAL=1
```

## Commands

| Command | What it does |
|---|---|
| `make dev` | Start all services |
| `make migrate` | Apply database migrations (`alembic upgrade head`) |
| `make seed` | Admin user, chart of accounts, GL mappings, periods |
| `make test` | Backend unit + integration tests |
| `make bench` | Golden benchmark replay |
| `make convert` | Regenerate benchmark cases X01/X02 from the Excel workbooks |
| `make lint` | ruff + mypy (backend), eslint + tsc (frontend) |
| `make load N=50000` | Performance run |

## Demo

[docs/demo-fyp1.md](docs/demo-fyp1.md) is the scripted FYP-I walkthrough, with its dataset and
screenshots. `make demo-reset CONFIRM=yes` **deletes all data in the development database** and
seeds it again, ready to present.

## Benchmarks

`benchmarks/source/` holds the Excel workbooks. `benchmarks/cases/<ID>/` holds one folder per
golden case (plan §11.3): `case.yaml`, `inputs/<YYYYMM>/*.csv` (one folder per replay month) and
`expected/*.csv`. Never edit a file under `expected/` to make a test pass.

## CI

`.github/workflows/ci.yml` runs on every pull request: ruff, mypy, migrations, pytest
(unit, integration, benchmarks) against PostgreSQL 16, and ESLint, Prettier, tsc and
`next build` for the frontend.
