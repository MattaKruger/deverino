"""Tests for semantic_retrieval — query composition, retrieval, and rendering."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from harness_poc.core.context_map.config import CartographerConfig
from harness_poc.core.context_map.schema import MapEntry
from harness_poc.core.storage.database import BlackboardDatabase


def _make_entry(*, priority: float = 0.8, summary: str = "A fact.") -> MapEntry:
    now = datetime.now(tz=UTC)
    return MapEntry(
        entry_id=str(uuid4()),
        key=f"k-{uuid4().hex[:6]}",
        section="domain_constants",
        observation_type="schema",
        summary=summary,
        priority=priority,
        source_event_ids=[],
        first_seen=now,
        last_updated=now,
        materialization_count=0,
        first_seen_cycle=1,
        last_seen_cycle=1,
        token_estimate=10,
    )


def _make_config(
    *,
    mode: str = "semantic",
    related: dict[str, list[str]] | None = None,
    semantic_top_k: int = 5,
    min_similarity: float = 0.3,
) -> SimpleNamespace:
    return SimpleNamespace(
        cartographer=CartographerConfig(
            cross_corpus_enabled=True,
            cross_corpus_related_corpora=related or {},
            cross_corpus_retrieval=mode,
            cross_corpus_semantic_top_k=semantic_top_k,
            cross_corpus_min_similarity=min_similarity,
            cross_corpus_query_turns=3,
            cross_corpus_query_max_chars=4000,
        ),
    )


class TestComposeQuery:
    def test_extracts_user_turns_from_messages(self) -> None:
        from harness_poc.core.context_map.semantic_retrieval import compose_query

        messages = [
            SimpleNamespace(role="user", content="how does auth work?"),
            SimpleNamespace(role="assistant", content="Auth uses JWT."),
            SimpleNamespace(role="user", content="where is the config?"),
        ]
        query = compose_query(messages, n_turns=3, max_chars=4000)
        assert "how does auth work?" in query
        assert "where is the config?" in query

    def test_respects_n_turns_limit(self) -> None:
        from harness_poc.core.context_map.semantic_retrieval import compose_query

        messages = [
            SimpleNamespace(role="user", content="old question"),
            SimpleNamespace(role="user", content="recent question"),
        ]
        query = compose_query(messages, n_turns=1, max_chars=4000)
        assert "recent question" in query
        assert "old question" not in query

    def test_truncates_at_max_chars(self) -> None:
        from harness_poc.core.context_map.semantic_retrieval import compose_query

        long_text = "x" * 5000
        messages = [SimpleNamespace(role="user", content=long_text)]
        query = compose_query(messages, n_turns=1, max_chars=100)
        assert len(query) <= 100

    def test_empty_messages_returns_empty(self) -> None:
        from harness_poc.core.context_map.semantic_retrieval import compose_query

        assert compose_query([], n_turns=3, max_chars=4000) == ""


class TestPriorityRetrieve:
    def test_returns_entries_sorted_by_priority(self) -> None:
        from harness_poc.core.context_map.semantic_retrieval import priority_retrieve

        db = BlackboardDatabase.from_url("sqlite:///:memory:")
        related = "deverino:related"
        entries = [
            _make_entry(priority=0.8, summary="Lower priority."),
            _make_entry(priority=0.9, summary="High priority."),
        ]
        db.write_map_and_mark_processed(related, entries, 20, [])
        config = _make_config(
            mode="deterministic",
            related={"deverino:codebase": [related]},
        )
        result = priority_retrieve(db, config, "deverino:codebase")
        assert len(result) == 2
        assert result[0][0].priority == 0.9
        assert result[1][0].priority == 0.8

    def test_filters_below_min_priority(self) -> None:
        from harness_poc.core.context_map.semantic_retrieval import priority_retrieve

        db = BlackboardDatabase.from_url("sqlite:///:memory:")
        related = "deverino:related"
        entries = [
            _make_entry(priority=0.5, summary="Below threshold."),
            _make_entry(priority=0.8, summary="Above threshold."),
        ]
        db.write_map_and_mark_processed(related, entries, 20, [])
        config = _make_config(
            mode="deterministic",
            related={"deverino:codebase": [related]},
        )
        # min_priority defaults to 0.7 in CartographerConfig
        result = priority_retrieve(db, config, "deverino:codebase")
        assert len(result) == 1
        assert result[0][0].priority == 0.8


class TestRenderBlock:
    def test_renders_corpus_header_and_entries(self) -> None:
        from harness_poc.core.context_map.semantic_retrieval import render_block

        entries = [
            (_make_entry(priority=0.9, summary="Important fact."), 0.85),
            (_make_entry(priority=0.7, summary="Related fact."), 0.62),
        ]
        block = render_block(entries, mode="semantic")
        assert "Related Corpora" in block
        assert "[entry:" in block
        assert "Important fact." in block

    def test_empty_entries_returns_empty(self) -> None:
        from harness_poc.core.context_map.semantic_retrieval import render_block

        assert render_block([], mode="semantic") == ""

    def test_semantic_mode_includes_similarity_score(self) -> None:
        from harness_poc.core.context_map.semantic_retrieval import render_block

        entries = [(_make_entry(summary="Test."), 0.85)]
        block = render_block(entries, mode="semantic")
        assert "sim=0.85" in block or "sim=0.850" in block

    def test_deterministic_mode_includes_priority(self) -> None:
        from harness_poc.core.context_map.semantic_retrieval import render_block

        entries = [(_make_entry(priority=0.9, summary="Test."), 0.9)]
        block = render_block(entries, mode="deterministic")
        assert "p=0.90" in block



class TestSemanticRetrieve:
    """Tests for semantic_retrieve() — cosine similarity ranking logic."""

    def test_returns_entries_ranked_by_similarity(self) -> None:
        from harness_poc.core.context_map.semantic_retrieval import semantic_retrieve

        db = BlackboardDatabase.from_url("sqlite:///:memory:")
        related = "deverino:related"
        entry_a = _make_entry(summary="The auth module uses JWT tokens.")
        entry_b = _make_entry(summary="React frontend with TypeScript.")
        db.write_map_and_mark_processed(
            related, [entry_a, entry_b], token_count=20, event_ids=["e1", "e2"]
        )

        config = _make_config(related={"deverino:codebase": [related]})

        # Query embedding closer to entry_a than entry_b
        # Normalized vectors: dot product = cosine similarity
        query_emb = [1.0] * 768
        entry_a_emb = [0.9] * 768
        entry_b_emb = [0.1] * 768

        # Mock retrieval_get_embeddings to return controlled vectors
        original = db.retrieval_get_embeddings
        db.retrieval_get_embeddings = lambda _ck: [  # type: ignore[method-assign]
            (entry_a.entry_id.replace("-", ""), entry_a_emb),
            (entry_b.entry_id.replace("-", ""), entry_b_emb),
        ]
        try:
            results = semantic_retrieve(db, config, "deverino:codebase", query_emb)
        finally:
            db.retrieval_get_embeddings = original  # type: ignore[method-assign]

        assert len(results) == 2
        # Entry A should rank higher (higher similarity)
        assert results[0][0].entry_id == entry_a.entry_id
        assert results[0][1] > results[1][1]

    def test_filters_below_min_similarity(self) -> None:
        from harness_poc.core.context_map.semantic_retrieval import semantic_retrieve

        db = BlackboardDatabase.from_url("sqlite:///:memory:")
        related = "deverino:related"
        entry = _make_entry(summary="Unrelated fact.")
        db.write_map_and_mark_processed(
            related, [entry], token_count=10, event_ids=["e1"]
        )

        config = _make_config(related={"deverino:codebase": [related]}, min_similarity=0.8)

        query_emb = [1.0] * 768
        low_sim_emb = [0.1] * 768  # dot product ~0.1, below 0.8 threshold

        original = db.retrieval_get_embeddings
        db.retrieval_get_embeddings = lambda _ck: [  # type: ignore[method-assign]
            (entry.entry_id.replace("-", ""), low_sim_emb),
        ]
        try:
            results = semantic_retrieve(db, config, "deverino:codebase", query_emb)
        finally:
            db.retrieval_get_embeddings = original  # type: ignore[method-assign]

        assert len(results) == 0

    def test_falls_back_to_priority_when_no_embeddings(self) -> None:
        from harness_poc.core.context_map.semantic_retrieval import semantic_retrieve

        db = BlackboardDatabase.from_url("sqlite:///:memory:")
        related = "deverino:related"
        entry = _make_entry(priority=0.9, summary="High priority fact.")
        db.write_map_and_mark_processed(
            related, [entry], token_count=10, event_ids=["e1"]
        )

        config = _make_config(related={"deverino:codebase": [related]})

        # retrieval_get_embeddings returns empty (no embeddings stored)
        original = db.retrieval_get_embeddings
        db.retrieval_get_embeddings = lambda _ck: []  # type: ignore[method-assign]
        try:
            results = semantic_retrieve(db, config, "deverino:codebase", [0.5] * 768)
        finally:
            db.retrieval_get_embeddings = original  # type: ignore[method-assign]

        assert len(results) == 1
        assert results[0][0].entry_id == entry.entry_id
        # Fallback entries have priority as score
        assert results[0][1] == 0.9

    def test_caps_at_semantic_top_k_per_corpus(self) -> None:
        from harness_poc.core.context_map.semantic_retrieval import semantic_retrieve

        db = BlackboardDatabase.from_url("sqlite:///:memory:")
        related = "deverino:related"
        entries = [_make_entry(summary=f"Fact {i}.") for i in range(10)]
        db.write_map_and_mark_processed(
            related, entries, token_count=100, event_ids=[f"e{i}" for i in range(10)]
        )

        config = _make_config(related={"deverino:codebase": [related]}, semantic_top_k=3)

        query_emb = [1.0] * 768
        embeddings = [
            (e.entry_id.replace("-", ""), [0.5] * 768) for e in entries
        ]

        original = db.retrieval_get_embeddings
        db.retrieval_get_embeddings = lambda _ck: embeddings  # type: ignore[method-assign]
        try:
            results = semantic_retrieve(db, config, "deverino:codebase", query_emb)
        finally:
            db.retrieval_get_embeddings = original  # type: ignore[method-assign]

        assert len(results) == 3  # capped at semantic_top_k

    def test_returns_empty_when_no_related_corpora(self) -> None:
        from harness_poc.core.context_map.semantic_retrieval import semantic_retrieve

        db = BlackboardDatabase.from_url("sqlite:///:memory:")
        config = _make_config(related={})
        results = semantic_retrieve(db, config, "deverino:codebase", [0.5] * 768)
        assert results == []
