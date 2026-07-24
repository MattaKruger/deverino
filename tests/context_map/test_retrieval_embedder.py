"""Tests for RetrievalEmbedder — bge-base-en-v1.5 wrapper for semantic retrieval."""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import numpy as np
import pytest

from harness_poc.core.context_map.retrieval_embedder import RetrievalEmbedder


class TestRetrievalEmbedder:
    def test_embed_query_returns_768_dim_vector(self) -> None:
        embedder = RetrievalEmbedder()
        vec = embedder.embed_query("how does authentication work?")
        assert len(vec) == 768
        assert all(isinstance(x, float) for x in vec)

    def test_embed_entries_returns_correct_count(self) -> None:
        embedder = RetrievalEmbedder()
        summaries = [
            "The auth module uses JWT tokens.",
            "Configuration lives in harness.yaml.",
        ]
        vectors = embedder.embed_entries(summaries)
        assert len(vectors) == 2
        for v in vectors:
            assert len(v) == 768

    def test_embed_entries_empty_returns_empty(self) -> None:
        embedder = RetrievalEmbedder()
        assert embedder.embed_entries([]) == []

    def test_similar_queries_have_high_cosine_similarity(self) -> None:
        embedder = RetrievalEmbedder()
        v1 = embedder.embed_query("database connection configuration")
        v2 = embedder.embed_query("how to configure the database connection")
        sim = float(np.dot(v1, v2))
        assert sim > 0.5, f"Expected similar queries sim > 0.5, got {sim:.3f}"
