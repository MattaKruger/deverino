from __future__ import annotations

import os

import pytest
from sqlalchemy import Engine, text
from sqlmodel import SQLModel

from harness_poc.core.db_engine import create_db_engine

# Override via env var when pointing at a dedicated test DB.
_DEFAULT_TEST_URL = "postgresql://deverino:deverino@localhost/deverino"
TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", _DEFAULT_TEST_URL)


@pytest.fixture(scope="session")
def _db_engine_session() -> Engine:
    """Create tables once per test session."""
    engine = create_db_engine(TEST_DATABASE_URL)
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture
def db_engine(_db_engine_session: Engine) -> Engine:
    """Return a clean engine with all tables truncated before each test."""
    table_names = ", ".join(f'"{t.name}"' for t in reversed(SQLModel.metadata.sorted_tables))
    with _db_engine_session.begin() as conn:
        conn.execute(text(f"TRUNCATE {table_names} RESTART IDENTITY CASCADE"))
    return _db_engine_session
