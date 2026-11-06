"""FastAPI app factory (plan §3, §8)."""

from fastapi import FastAPI

from app.api.errors import install_error_handlers
from app.api.v1 import api_router


def create_app() -> FastAPI:
    app = FastAPI(title="Revenue Recognition System", version="0.1.0")
    install_error_handlers(app)
    app.include_router(api_router, prefix="/api/v1")
    return app


app = create_app()
