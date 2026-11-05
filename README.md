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

Requires Docker Desktop (running, with "Engine running" showing) and `make`. On Windows, one way to get `make` is `winget install ezwinports.make`, then open a new terminal.

In a terminal in the project folder:

```bash
cp .env.example .env   # Windows PowerShell: copy .env.example .env
make dev               # builds and starts postgres, api, worker, web; leave it running
```

The first build can take 15 minutes or more. It is ready when http://localhost:3000 opens. Until the next step, the terminal shows database errors from the worker; that is normal. Open a **second** terminal in the same folder and set up the database once:

```bash
make migrate
make seed
```

Open http://localhost:3000 and sign in with `admin@revrec.local` / `ChangeMe-Admin1`. The dashboard should show the current period and `API: ok`. **Change this password before using real data.**

To learn the app, follow [docs/user-manual.md](docs/user-manual.md). To stop it, press Ctrl+C in the first terminal, or run `make down`; your data is kept. If a port is already in use, close whatever uses 3000, 8000 or 5432.

## Run without Docker

Requires Python 3.12, Node.js 20+, PostgreSQL 16 and `make`. Create a `revrec` user and database first, then run `alembic upgrade head` and `python ../tools/seed.py` from `backend/`.

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
| `make stress S=6 LINES=200` | More generated datasets, hunting for bugs |
| `make report` | Run the benchmarks, then write `docs/test-report/test-report.md` and `.pdf` |
| `make convert` | Regenerate benchmark cases X01/X02 from the Excel workbooks |
| `make lint` | ruff + mypy (backend), eslint + tsc (frontend) |
| `make load N=50000` | Load test on its own database (`revrec_load`), never your data |

## Demo

Other documents: [user manual](docs/user-manual.md), [performance results](docs/performance.md), [validation log](docs/validation-log.md), [security pass](docs/security-pass.md), [test report](docs/test-report/test-report.md).

[docs/demo-viva.md](docs/demo-viva.md) is the full viva demo; `make demo-viva CONFIRM=yes` **deletes all data in the development database** and sets it up. The release steps are in [docs/release/release-checklist.md](docs/release/release-checklist.md), and `make release-archive` archives the schema.

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
