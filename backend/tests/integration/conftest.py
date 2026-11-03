"""Integration fixtures: a separate test database so tests never touch dev data.

The test database is REVREC_TEST_DATABASE_URL, or REVREC_DATABASE_URL with `_test`
appended to the database name. It is created on first use.
"""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, create_engine, text
from sqlalchemy.engine import URL, make_url

from app.config import get_settings

BACKEND = Path(__file__).resolve().parents[2]


def _test_url() -> URL:
    explicit = os.environ.get("REVREC_TEST_DATABASE_URL")
    if explicit:
        return make_url(explicit)
    url = make_url(get_settings().database_url)
    return url.set(database=f"{url.database}_test")


@pytest.fixture(scope="session")
def test_db_url() -> str:
    url = _test_url()
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": url.database}
        ).scalar()
        if not exists:
            # The name comes from configuration, never from user input.
            conn.execute(text(f'CREATE DATABASE "{url.database}"'))
    admin.dispose()
    return url.render_as_string(hide_password=False)


@pytest.fixture(scope="session")
def alembic_config(test_db_url: str) -> Config:
    cfg = Config()  # no ini file: keeps Alembic from reconfiguring pytest's logging
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    cfg.set_main_option("sqlalchemy.url", test_db_url.replace("%", "%%"))
    return cfg


@pytest.fixture(scope="session")
def migrated_engine(alembic_config: Config, test_db_url: str) -> Iterator[Engine]:
    """Test database upgraded to the latest migration."""
    command.upgrade(alembic_config, "head")
    engine = create_engine(test_db_url)
    yield engine
    engine.dispose()


@pytest.fixture
def conn(migrated_engine: Engine) -> Iterator[Connection]:
    """A connection inside a transaction that is rolled back after the test."""
    with migrated_engine.connect() as connection:
        transaction = connection.begin()
        yield connection
        transaction.rollback()
