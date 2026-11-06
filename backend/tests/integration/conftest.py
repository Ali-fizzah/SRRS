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
from fastapi.testclient import TestClient
from sqlalchemy import Connection, Engine, create_engine, select, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session, sessionmaker

from app.auth.rate_limit import login_limiter
from app.auth.roles import Role
from app.auth.tokens import create_access_token
from app.config import get_settings
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import Role as RoleRow
from app.models import User, UserRole

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


@pytest.fixture
def db(conn: Connection) -> Iterator[Session]:
    """ORM session inside the test transaction; its commits become savepoints."""
    with Session(bind=conn, join_transaction_mode="create_savepoint") as session:
        yield session


@pytest.fixture
def client(db: Session) -> Iterator[TestClient]:
    """API client whose requests use the test transaction."""
    login_limiter.reset()
    app.dependency_overrides[get_db] = lambda: db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def committed(migrated_engine: Engine) -> Iterator[sessionmaker[Session]]:
    """Sessions that really commit, for code using several connections (the job queue).

    Everything is wiped afterwards. TRUNCATE is the one way past the append-only triggers;
    `roles` stays because a migration created it.
    """
    yield sessionmaker(bind=migrated_engine, autoflush=False, expire_on_commit=False)
    names = ", ".join(t.name for t in Base.metadata.sorted_tables if t.name != "roles")
    with migrated_engine.begin() as connection:
        connection.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))


@pytest.fixture
def committed_client(committed: sessionmaker[Session]) -> Iterator[TestClient]:
    """API client whose requests commit for real, one session per request."""

    def session_per_request() -> Iterator[Session]:
        with committed() as session:
            yield session

    app.dependency_overrides[get_db] = session_per_request
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def make_user(
    db: Session,
    roles: list[Role],
    *,
    email: str | None = None,
    password_hash: str = "not-a-real-hash",
    is_active: bool = True,
) -> User:
    user = User(
        email=email or f"{'-'.join(r.lower() for r in roles) or 'norole'}@test.local",
        full_name="Test User",
        password_hash=password_hash,
        is_active=is_active,
    )
    db.add(user)
    db.flush()
    role_ids = dict(db.execute(select(RoleRow.name, RoleRow.id)).tuples().all())
    for role in roles:
        db.add(UserRole(user_id=user.id, role_id=role_ids[role.value]))
    db.flush()
    return user


def use_token(client: TestClient, token: str | None) -> None:
    """Make `client` send this session cookie (None = signed out)."""
    client.cookies.clear()
    if token is not None:
        client.cookies.set(get_settings().cookie_name, token)


def sign_in(client: TestClient, user: User) -> None:
    """Make `client` act as `user` from now on."""
    use_token(client, create_access_token(user.id))
