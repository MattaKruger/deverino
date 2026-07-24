"""Tests for retrieval embedding storage — context_map_retrieval_embeddings table."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine

from harness_poc.core.storage.database import BlackboardDatabase


class TestRetrievalSqliteNoop:
    """All retrieval methods return safe defaults on SQLite (no pgvector)."""

    @pytest.fixture
    def sqlite_db(self):
        engine = create_engine("sqlite://", echo=False)
        db = BlackboardDatabase(engine)
        db.create_tables()
        return db

    def test_retrieval_is_available_returns_false(self, sqlite_db) -> None:
        assert sqlite_db.retrieval_is_available() is False

    def test_retrieval_ensure_schema_noop(self, sqlite_db) -> None:
        sqlite_db.retrieval_ensure_schema()

    def test_retrieval_upsert_embeddings_noop(self, sqlite_db) -> None:
        sqlite_db.retrieval_upsert_embeddings(
            "corpus-1",
            [("key-1", [0.1] * 768)],
        )

    def test_retrieval_get_embeddings_returns_empty(self, sqlite_db) -> None:
        result = sqlite_db.retrieval_get_embeddings("corpus-1")
        assert result == []


class TestRetrievalPostgres:
    """Integration tests on PostgreSQL with pgvector. Uses db_engine fixture."""

    def test_upsert_and_get_embeddings(self, db_engine) -> None:
        db = BlackboardDatabase(db_engine)
        if not db.retrieval_is_available():
            pytest.skip("pgvector not available")

        entries = [
            ("entry-a", [0.1] * 768),
            ("entry-b", [0.2] * 768),
        ]
        db.retrieval_upsert_embeddings("test-corpus", entries)

        result = db.retrieval_get_embeddings("test-corpus")
        assert len(result) == 2
        keys = {k for k, _ in result}
        assert keys == {"entry-a", "entry-b"}

    def test_upsert_replaces_old_embeddings(self, db_engine) -> None:
        db = BlackboardDatabase(db_engine)
        if not db.retrieval_is_available():
            pytest.skip("pgvector not available")

        db.retrieval_upsert_embeddings("test-corpus", [("old-entry", [0.1] * 768)])
        db.retrieval_upsert_embeddings("test-corpus", [("new-entry", [0.2] * 768)])

        result = db.retrieval_get_embeddings("test-corpus")
        assert len(result) == 1
        assert result[0][0] == "new-entry"

    def test_get_embeddings_empty_corpus(self, db_engine) -> None:
        db = BlackboardDatabase(db_engine)
        if not db.retrieval_is_available():
            pytest.skip("pgvector not available")
        assert db.retrieval_get_embeddings("nonexistent") == []
