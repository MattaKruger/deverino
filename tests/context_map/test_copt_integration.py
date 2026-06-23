"""Integration tests for CopT Gate with real pgvector.

Requires the test PostgreSQL container on localhost:5433 with the vector
extension installed. Uses the existing db_engine fixture from conftest.py.
"""

from __future__ import annotations

import pytest
from sqlalchemy import Engine, text

from harness_poc.core.storage.database import BlackboardDatabase

np = pytest.importorskip("numpy", reason="numpy required for CopT tests")


class TestCoptPgvectorIntegration:
    """CopT gate exercises real pgvector extension."""

    def test_copt_is_available_returns_true(self, db_engine: Engine) -> None:
        db = BlackboardDatabase(db_engine)
        assert db.copt_is_available() is True

    def test_upsert_and_query_similarity(self, db_engine: Engine) -> None:
        db = BlackboardDatabase(db_engine)

        emb = list(np.random.randn(384).astype(float))
        corpus = "copt_integration_test"
        entry_key = "test-key-1"

        db.copt_upsert_embeddings(corpus, [(entry_key, emb)])
        sim = db.copt_query_similarity(corpus, emb)

        # Same vector should have cosine similarity close to 1.0
        assert sim > 0.99, f"Expected sim > 0.99 for identical vector, got {sim:.4f}"

        # Cleanup
        with db_engine.begin() as conn:
            conn.execute(
                text("DELETE FROM context_map_embeddings WHERE corpus_key = :c"),
                {"c": corpus},
            )

    def test_different_vectors_have_lower_similarity(self, db_engine: Engine) -> None:
        db = BlackboardDatabase(db_engine)

        emb1 = list((np.random.randn(384) * 0.1).astype(float))
        emb2 = list((np.random.randn(384) * 10.0 + 5.0).astype(float))
        corpus = "copt_integration_diff"
        entry_key = "diff-key"

        db.copt_upsert_embeddings(corpus, [(entry_key, emb1)])
        sim = db.copt_query_similarity(corpus, emb2)

        # Very different vectors should have similarity well below 0.99
        assert sim < 0.99, f"Expected different vectors to have sim < 0.99, got {sim:.4f}"

        # Cleanup
        with db_engine.begin() as conn:
            conn.execute(
                text("DELETE FROM context_map_embeddings WHERE corpus_key = :c"),
                {"c": corpus},
            )

    def test_query_nonexistent_corpus_returns_zero(self, db_engine: Engine) -> None:
        db = BlackboardDatabase(db_engine)
        emb = list(np.random.randn(384).astype(float))
        sim = db.copt_query_similarity("nonexistent_corpus_xyz", emb)
        assert sim == 0.0

    def test_upsert_overwrites_existing_key(self, db_engine: Engine) -> None:
        db = BlackboardDatabase(db_engine)

        emb_old = list(np.ones(384, dtype=float))
        emb_new = list((np.random.randn(384) * 10.0).astype(float))
        corpus = "copt_integration_overwrite"
        entry_key = "overwrite-key"

        db.copt_upsert_embeddings(corpus, [(entry_key, emb_old)])
        db.copt_upsert_embeddings(corpus, [(entry_key, emb_new)])

        # Query with new vector should match (overwritten)
        sim_new = db.copt_query_similarity(corpus, emb_new)
        assert sim_new > 0.99, f"Expected sim > 0.99 for overwritten vector, got {sim_new:.4f}"

        # Cleanup
        with db_engine.begin() as conn:
            conn.execute(
                text("DELETE FROM context_map_embeddings WHERE corpus_key = :c"),
                {"c": corpus},
            )

    def test_copt_ensure_schema_idempotent(self, db_engine: Engine) -> None:
        """Calling copt_ensure_schema twice should succeed without error."""
        db = BlackboardDatabase(db_engine)
        db.copt_ensure_schema()
        db.copt_ensure_schema()
        # No exception = pass
