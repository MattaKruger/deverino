from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from harness_poc.api.routes import router
from harness_poc.core.storage.db_engine import create_db_engine


def create_app(database_url: str) -> FastAPI:
    """Create a FastAPI application wired to the given database URL."""
    app = FastAPI(title="Deverino Dashboard")
    engine = create_db_engine(database_url)
    app.state.engine = engine

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(router)

    dist_path = Path(__file__).resolve().parent.parent.parent / "dashboard-ui" / "dist"
    if dist_path.exists():
        app.mount("/", StaticFiles(directory=str(dist_path), html=True))

    return app


def create_app_from_config() -> FastAPI:
    """Factory for uvicorn reload mode — reads config and creates the app."""
    from harness_poc.core.config import HarnessConfig  # noqa: PLC0415

    config = HarnessConfig.load()
    return create_app(config.runtime.database_url)
