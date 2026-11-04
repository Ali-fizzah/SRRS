"""Application settings, read from environment variables with the REVREC_ prefix."""

from datetime import date
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="REVREC_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://revrec:revrec@localhost:5432/revrec"
    # HS256 needs at least 32 bytes of key; the app refuses to start with less.
    jwt_secret: str = Field(default="dev-only-insecure-jwt-secret-change-me-0001", min_length=32)
    jwt_expire_minutes: int = 480
    cookie_name: str = "revrec_session"
    cookie_secure: bool = False  # True when served over HTTPS
    upload_dir: str = "storage/uploads"
    max_upload_bytes: int = 50 * 1024 * 1024  # per file
    worker_poll_seconds: float = 1.0

    # Period `make seed` opens when it first creates the periods (D6). YYYYMM;
    # empty or unset means the current calendar month.
    current_period: str = Field(
        default="", pattern=r"^(\d{4}(0[1-9]|1[0-2]))?$", validate_default=True
    )

    @field_validator("current_period")
    @classmethod
    def _default_to_this_month(cls, value: str) -> str:
        return value or date.today().strftime("%Y%m")

    # First admin, created by `make seed` if no user has that email yet.
    admin_email: str = "admin@revrec.local"
    admin_password: str = "ChangeMe-Admin1"
    admin_name: str = "Administrator"


@lru_cache
def get_settings() -> Settings:
    return Settings()
