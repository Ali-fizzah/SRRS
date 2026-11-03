"""P1-T1: the migration builds every table in plan §6.1 and can be fully reversed."""

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text

import app.models  # noqa: F401  (registers every table)
from app.db.base import Base


def _user_tables(url: str) -> set[str]:
    engine = create_engine(url)
    try:
        return set(inspect(engine).get_table_names()) - {"alembic_version"}
    finally:
        engine.dispose()


def _enum_count(url: str) -> int:
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            return int(
                conn.execute(text("SELECT count(*) FROM pg_type WHERE typtype = 'e'")).scalar_one()
            )
    finally:
        engine.dispose()


def test_upgrade_matches_models_and_downgrade_removes_everything(
    alembic_config: Config, test_db_url: str
) -> None:
    command.downgrade(alembic_config, "base")  # start clean even if a previous run stopped midway

    command.upgrade(alembic_config, "head")
    assert _user_tables(test_db_url) == set(Base.metadata.tables)

    engine = create_engine(test_db_url)
    try:
        with engine.connect() as conn:
            diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    finally:
        engine.dispose()
    assert diff == [], f"models and migration differ: {diff}"

    command.downgrade(alembic_config, "base")
    assert _user_tables(test_db_url) == set()
    assert _enum_count(test_db_url) == 0

    command.upgrade(alembic_config, "head")  # and it can be applied again
    assert _user_tables(test_db_url) == set(Base.metadata.tables)
