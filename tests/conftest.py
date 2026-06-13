from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel

from harness_poc.core.config import (
    HarnessConfig,
    HarnessPaths,
    LLMConfig,
    ObservabilityConfig,
    RuntimeConfig,
)
from harness_poc.core.skills import SkillRunner
from harness_poc.core.storage import BlackboardDatabase, create_db_engine

# Skip the Vespa auto-index bootstrap for any test that reaches AppState.
# Reindexing the docs/ tree takes minutes and is unrelated to anything the
# test suite verifies; integration tests opt back in explicitly.
os.environ.setdefault("HARNESS_SKIP_AUTO_INDEX", "1")

# Override via env var when pointing at a dedicated test DB.
DEFAULT_TEST_DATABASE_URL = "postgresql://deverino_test:deverino_test@localhost:5433/deverino_test"
TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL)


@pytest.fixture(scope="session")
def _db_engine_session() -> Engine:
    """Create tables once per test session."""
    engine = create_db_engine(TEST_DATABASE_URL)
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture
def db_engine(_db_engine_session: Engine) -> Engine:
    """Return a clean engine with all tables truncated before each test."""
    with _db_engine_session.begin() as conn:
        if _db_engine_session.dialect.name == "postgresql":
            table_names = ", ".join(
                f'"{t.name}"' for t in reversed(SQLModel.metadata.sorted_tables)
            )
            conn.execute(text(f"TRUNCATE {table_names} RESTART IDENTITY CASCADE"))
        else:
            for table in reversed(SQLModel.metadata.sorted_tables):
                conn.execute(table.delete())
    return _db_engine_session


@pytest.fixture
def in_memory_engine() -> Engine:
    """In-memory SQLite engine with full schema. Use for unit + agent tests."""
    # Import database to ensure all SQLModel table classes are registered
    # before create_all runs. Without this, SQLModel.metadata is empty and
    # no tables are created in the in-memory database.
    import harness_poc.core.storage.database  # noqa: F401 — triggers model registration

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture
def test_config(db_engine: Engine) -> HarnessConfig:
    """HarnessConfig wired to real project paths and the test database."""
    repo_root = Path.cwd()
    return HarnessConfig(
        project_root=repo_root,
        config_path=repo_root / "harness.yaml",
        paths=HarnessPaths(
            soul=repo_root / "harness_poc/system_prompts/SOUL.md",
            system_tools=repo_root / "harness_poc/system_tools",
            system_skills=repo_root / "harness_poc/system_skills",
            project_skills=repo_root / "skills",
            workflows=repo_root / "workflows",
            pipelines=repo_root / "pipelines",
            personas=repo_root / "personas",
        ),
        runtime=RuntimeConfig(
            database_url=db_engine.url.render_as_string(hide_password=False),
            default_container_image="python:3.14-slim",
        ),
        observability=ObservabilityConfig(logfire_enabled=False),
        llm=LLMConfig(provider="deepseek", model="deepseek-v4-flash", base_url=None),
    )


@pytest.fixture
def session_runner(
    test_config: HarnessConfig, db_engine: Engine
) -> tuple[SkillRunner, str, BlackboardDatabase]:
    """Bootstrap a session + SkillRunner. Returns (runner, session_id, database)."""
    database = BlackboardDatabase(db_engine)
    session_id = database.start_session("test")
    runner = SkillRunner(database=database, config=test_config)
    return runner, session_id, database
