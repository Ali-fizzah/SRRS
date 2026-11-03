"""P1-T3: `make seed` creates the first admin once and is safe to run again."""

import importlib.util
import sys
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import User

REPO = Path(__file__).resolve().parents[3]


def _seed_module():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("seed", REPO / "tools" / "seed.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_seed_admin_is_idempotent_and_can_sign_in(client: TestClient, db: Session) -> None:
    seed = _seed_module()
    settings = Settings(admin_email="Seed.Admin@test.local", admin_password="Seed-Pass-123")

    assert seed.seed_admin(db, settings) is True
    assert seed.seed_admin(db, settings) is False  # second run changes nothing
    count = db.scalar(select(func.count()).where(User.email == "seed.admin@test.local"))
    assert count == 1

    response = client.post(
        "/api/v1/auth/login",
        json={"email": "seed.admin@test.local", "password": "Seed-Pass-123"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["roles"] == ["ADMIN"]
