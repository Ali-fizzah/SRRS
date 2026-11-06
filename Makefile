# Developer commands (plan §3, CLAUDE.md "Commands").
#
# By default every command runs inside docker-compose.
# Without Docker, activate backend/.venv and pass LOCAL=1, e.g. `make test LOCAL=1`.

ifdef LOCAL
BACKEND = cd backend &&
WEB     = cd frontend &&
else
BACKEND = docker compose run --rm api
WEB     = docker compose run --rm web
endif

N ?= 50000

.PHONY: dev down migrate seed test lint bench stress report convert erd load demo-reset demo-viva release-archive

# -V: renew the web container's node_modules volume, or new npm packages stay invisible.
dev:
	docker compose up --build -V

down:
	docker compose down

migrate:
	$(BACKEND) alembic upgrade head

seed:
	$(BACKEND) python ../tools/seed.py

test:
	$(BACKEND) pytest tests/unit tests/integration -q

lint:
	$(BACKEND) ruff check . ../benchmarks/tools ../tools
	$(BACKEND) ruff format --check . ../benchmarks/tools ../tools
	$(BACKEND) mypy
	$(WEB) npm run lint
	$(WEB) npm run typecheck

bench:
	$(BACKEND) pytest tests/benchmarks -q

# Hunt for bugs with generated datasets, more than `make bench` can afford (task P6-T3).
S ?= 5
LINES ?= 300
stress:
	$(BACKEND) env REVREC_STRESS=$(S):$(LINES) pytest tests/benchmarks/test_generated_datasets.py -q -k stress

# Run the benchmarks, then write docs/test-report/test-report.md and .pdf (task P6-T4).
report:
	-$(BACKEND) pytest tests/benchmarks -q
	$(BACKEND) python ../tools/test_report.py --repo .. --commit $(shell git describe --always --dirty)

# Regenerate the Excel benchmark cases X01/X02 from benchmarks/source (plan §11.4).
convert:
	$(BACKEND) python ../benchmarks/tools/convert_revrec_xlsx.py ../benchmarks/source/REVREC_Model_Final.xlsx ../benchmarks/cases/X01_revrec_model_final
	$(BACKEND) python ../benchmarks/tools/convert_revrec_xlsx.py ../benchmarks/source/REVREC_Mock_Data.xlsx ../benchmarks/cases/X02_revrec_mock_data

# Regenerate docs/erd.md from the SQLAlchemy models.
erd:
	$(BACKEND) python ../tools/gen_erd.py ../docs/erd.md

# Clean database for the demo (docs/demo-fyp1.md). DELETES ALL DATA in the dev database.
demo-reset:
ifneq ($(CONFIRM),yes)
	$(error This deletes all data in the dev database. Run: make demo-reset CONFIRM=yes)
endif
	docker compose exec -T postgres dropdb -U revrec --force revrec
	docker compose exec -T postgres createdb -U revrec revrec
	docker compose run --rm api alembic upgrade head
	docker compose run --rm -e REVREC_CURRENT_PERIOD=202612 api python ../tools/seed.py
	docker compose restart worker

# Clean database for the viva (docs/demo-viva.md), with May 2027 open and its three users.
# DELETES ALL DATA in the dev database.
demo-viva:
ifneq ($(CONFIRM),yes)
	$(error This deletes all data in the dev database. Run: make demo-viva CONFIRM=yes)
endif
	docker compose exec -T postgres dropdb -U revrec --force revrec
	docker compose exec -T postgres createdb -U revrec revrec
	docker compose run --rm api alembic upgrade head
	docker compose run --rm -e REVREC_CURRENT_PERIOD=202705 api python ../tools/seed.py
	docker compose run --rm api python ../tools/seed_demo_users.py
	docker compose restart api worker

# Archive the schema, from a throwaway database at the latest migration, and the ERD (task P8-T1).
release-archive:
	docker compose exec -T postgres dropdb -U revrec --force --if-exists revrec_schema
	docker compose exec -T postgres createdb -U revrec revrec_schema
	docker compose run --rm -e REVREC_DATABASE_URL=postgresql+psycopg://revrec:revrec@postgres:5432/revrec_schema api alembic upgrade head
	docker compose exec -T postgres pg_dump -U revrec --schema-only --no-owner --no-privileges revrec_schema > docs/release/schema.sql
	docker compose exec -T postgres dropdb -U revrec --force revrec_schema
	docker compose run --rm api python ../tools/gen_erd.py ../docs/erd.md

load:
	$(BACKEND) python ../tools/load_test.py --lines $(N)
