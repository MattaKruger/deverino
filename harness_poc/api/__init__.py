from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from harness_poc.api.chat import router as chat_router
from harness_poc.api.routes import router
from harness_poc.core.storage.db_engine import create_db_engine


def create_app(database_url: str) -> FastAPI:
    """Create a FastAPI application wired to the given database URL."""
    app = FastAPI(title="Deverino Dashboard")
    engine = create_db_engine(database_url)
    app.state.engine = engine
    app.state.active_tokens: dict = {}

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(router)
    app.include_router(chat_router)

    # Frontend is served by Vite dev server (`cd dashboard-ui && npx vite`).
    # For production deploys, build with `npx vite build` and serve dist/
    # via nginx or a dedicated static file server.

    return app


def create_app_from_config() -> FastAPI:
    """Factory for uvicorn reload mode — reads config and creates the app."""
    from harness_poc.core.config import HarnessConfig  # noqa: PLC0415
    from harness_poc.core.runtime.pydantic_runtime import (  # noqa: PLC0415
        build_model,
    )

    config = HarnessConfig.load()
    app = create_app(config.runtime.database_url)

    # Store config on app.state so chat and other endpoints can access it
    app.state.config = config

    # Preload the LLM model at startup so compilation requests don't
    # pay the cold-start cost on every POST /api/skills/compile call.
    try:
        if config.compiler.model or config.compiler.provider:
            from harness_poc.core.config import LLMConfig  # noqa: PLC0415

            llm_cfg = LLMConfig(
                provider=config.compiler.provider or config.llm.provider,
                model=config.compiler.model or config.llm.model,
                base_url=config.llm.base_url,
            )
        else:
            llm_cfg = config.llm
        app.state.compiler_model = build_model(llm_cfg)
    except Exception:
        app.state.compiler_model = None

    return app
