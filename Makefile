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

.PHONY: dev down migrate seed test lint bench convert load

dev:
	docker compose up --build

down:
	docker compose down

migrate:
	$(BACKEND) alembic upgrade head

seed:
	$(BACKEND) python ../tools/seed.py

test:
	$(BACKEND) pytest tests/unit tests/integration -q

lint:
	$(BACKEND) ruff check . ../benchmarks/tools
	$(BACKEND) ruff format --check . ../benchmarks/tools
	$(BACKEND) mypy
	$(WEB) npm run lint
	$(WEB) npm run typecheck

bench:
	$(BACKEND) pytest tests/benchmarks -q

# Regenerate the Excel benchmark cases X01/X02 from benchmarks/source (plan §11.4).
convert:
	$(BACKEND) python ../benchmarks/tools/convert_revrec_xlsx.py ../benchmarks/source/REVREC_Model_Final.xlsx ../benchmarks/cases/X01_revrec_model_final
	$(BACKEND) python ../benchmarks/tools/convert_revrec_xlsx.py ../benchmarks/source/REVREC_Mock_Data.xlsx ../benchmarks/cases/X02_revrec_mock_data

load:
	$(BACKEND) python ../tools/generate_dataset.py --lines $(N)
