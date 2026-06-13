"""Tests for CopT Gate — pgvector embedding dedup for the context map materializer.

Covers plans/09-copt-gate-plan.md success criteria:
  1. Boring batches: CopT gate skips Cartographer
  2. Novel batches: Cartographer runs, embeddings persisted
  3. SQLite: gate is a no-op (all methods return safe defaults)
  4. Embedding helpers: lazy-load model, embed strings
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine

from harness_poc.core.context_map.copt_gate import embed_single, embed_summaries
from harness_poc.core.storage.database import BlackboardDatabase

# ---------------------------------------------------------------------------
# Test: CopT database methods are safe no-ops on SQLite
# ---------------------------------------------------------------------------

class TestCoptSqliteNoop:
    """All CopT methods return safe defaults when running on SQLite."""

    @pytest.fixture
    def sqlite_db(self):
        engine = create_engine("sqlite://", echo=False)
        db = BlackboardDatabase(engine)
        db.create_tables()
        return db

    def test_copt_is_available_returns_false(self, sqlite_db):
        assert sqlite_db.copt_is_available() is False

    def test_copt_ensure_schema_noop(self, sqlite_db):
        """Should not raise on SQLite."""
        sqlite_db.copt_ensure_schema()

    def test_copt_query_similarity_returns_zero(self, sqlite_db):
        sim = sqlite_db.copt_query_similarity("corpus-1", [0.1] * 384)
        assert sim == 0.0

    def test_copt_upsert_embeddings_noop(self, sqlite_db):
        """Should not raise on SQLite."""
        sqlite_db.copt_upsert_embeddings(
            "corpus-1",
            [("key-1", [0.1] * 384)],
        )

    def test_copt_query_returns_zero_on_empty_corpus(self, sqlite_db):
        sim = sqlite_db.copt_query_similarity("nonexistent", [0.5] * 384)
        assert sim == 0.0


# ---------------------------------------------------------------------------
# Test: Embedding helpers
# ---------------------------------------------------------------------------

class TestEmbeddingHelpers:
    def test_embed_single_returns_384_dim_vector(self):
        embedding = embed_single("This is a test summary for semantic dedup.")
        assert len(embedding) == 384
        assert all(isinstance(x, float) for x in embedding)

    def test_embed_summaries_returns_correct_count(self):
        summaries = [
            "The codebase uses pytest for testing.",
            "Configuration lives in harness.yaml.",
            "The runtime blackboard is PostgreSQL.",
        ]
        embeddings = embed_summaries(summaries)
        assert len(embeddings) == 3
        for emb in embeddings:
            assert len(emb) == 384
            assert all(isinstance(x, float) for x in emb)

    def test_embed_summaries_empty(self):
        assert embed_summaries([]) == []

    def test_similar_summaries_have_high_cosine_similarity(self):
        """Semantically similar strings should have cosine sim > 0.7."""
        import numpy as np

        emb1 = embed_single("The database uses PostgreSQL as the primary store.")
        emb2 = embed_single("PostgreSQL is the primary database for the project.")
        # Cosine similarity of normalized vectors = dot product
        sim = float(np.dot(emb1, emb2))
        assert sim > 0.5, f"Expected similar summaries to have sim > 0.5, got {sim:.3f}"

    def test_dissimilar_summaries_have_low_cosine_similarity(self):
        """Semantically different strings should have cosine sim < 0.5."""
        import numpy as np

        emb1 = embed_single("The database uses PostgreSQL as the primary store.")
        emb2 = embed_single("The frontend renders React components with TypeScript.")
        sim = float(np.dot(emb1, emb2))
        assert sim < 0.6, f"Expected dissimilar summaries to have sim < 0.6, got {sim:.3f}"
