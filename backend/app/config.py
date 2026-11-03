"""Application settings, read from environment variables with the REVREC_ prefix."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="REVREC_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://revrec:revrec@localhost:5432/revrec"
    jwt_secret: str = "change-me-in-production"
    upload_dir: str = "storage/uploads"
    worker_poll_seconds: float = 1.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
