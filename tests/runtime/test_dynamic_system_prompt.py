"""Tests for the dynamic system prompt decorator — semantic vs deterministic ranking."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

from harness_poc.core.context_map.config import CartographerConfig
from harness_poc.core.context_map.schema import MapEntry
from harness_poc.core.runtime.pydantic_runtime import AgentDeps
from harness_poc.core.storage.database import BlackboardDatabase


def _make_deps(db: BlackboardDatabase, mode: str = "semantic") -> AgentDeps:
    config = SimpleNamespace(
        cartographer=CartographerConfig(
            cross_corpus_enabled=True,
            cross_corpus_related_corpora={"deverino:codebase": ["deverino:related"]},
            cross_corpus_retrieval=mode,
        ),
        project_id="deverino",
    )
    return AgentDeps(
        session_id="test-session",
        database=db,
        config=config,  # type: ignore[arg-type]
        skill_runner=MagicMock(),
        retrieval_mode=[mode],
    )


class TestRetrievalModeFlag:
    def test_deps_has_retrieval_mode_default(self) -> None:
        db = BlackboardDatabase.from_url("sqlite:///:memory:")
        deps = _make_deps(db)
        assert deps.retrieval_mode[0] == "semantic"

    def test_retrieval_mode_is_mutable(self) -> None:
        db = BlackboardDatabase.from_url("sqlite:///:memory:")
        deps = _make_deps(db, mode="deterministic")
        assert deps.retrieval_mode[0] == "deterministic"
        deps.retrieval_mode[0] = "semantic"
        assert deps.retrieval_mode[0] == "semantic"


class TestDynamicDecorator:
    """The decorator function itself, tested in isolation."""

    def test_deterministic_mode_returns_priority_block(self) -> None:
        from harness_poc.core.runtime.pydantic_runtime import _cross_corpus_decorator_fn

        db = BlackboardDatabase.from_url("sqlite:///:memory:")
        # Seed a related corpus with entries
        entry = MapEntry(
            entry_id="abc123",
            key="test-key",
            section="domain_constants",
            observation_type="schema",
            summary="A test fact.",
            priority=0.85,
            source_event_ids=[],
            first_seen=datetime.now(tz=UTC),
            last_updated=datetime.now(tz=UTC),
            materialization_count=0,
            first_seen_cycle=1,
            last_seen_cycle=1,
            token_estimate=10,
        )
        db.write_map_and_mark_processed("deverino:related", [entry], 10, [])

        deps = _make_deps(db, mode="deterministic")
        ctx = SimpleNamespace(deps=deps, messages=[])

        result = _cross_corpus_decorator_fn(ctx)
        assert "Related Corpora" in result
        assert "A test fact." in result
        assert "p=0.85" in result

    def test_returns_empty_when_cross_corpus_disabled(self) -> None:
        from harness_poc.core.runtime.pydantic_runtime import _cross_corpus_decorator_fn

        db = BlackboardDatabase.from_url("sqlite:///:memory:")
        config = SimpleNamespace(
            cartographer=CartographerConfig(cross_corpus_enabled=False),
            project_id="deverino",
        )
        deps = AgentDeps(
            session_id="test",
            database=db,
            config=config,  # type: ignore[arg-type]
            skill_runner=MagicMock(),
        )
        ctx = SimpleNamespace(deps=deps, messages=[])

        result = _cross_corpus_decorator_fn(ctx)
        assert result == ""
