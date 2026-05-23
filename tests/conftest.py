from __future__ import annotations

import os

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel

from harness_poc.core.storage import create_db_engine

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
    import harness_poc.core.storage.database  # noqa: F401, PLC0415 — triggers model registration

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine
