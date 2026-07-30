"""Tests for cross-corpus exclusion from static system prompt.

The old _render_cross_corpus() was deleted (replaced by semantic_retrieval.priority_retrieve()
+ render_block()). Cross-corpus is now handled exclusively by the dynamic decorator.
These tests verify the static prompt does NOT include cross-corpus.
"""
from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from harness_poc.core.context_map.schema import MapEntry
from harness_poc.core.storage.database import BlackboardDatabase


@pytest.fixture
def db() -> BlackboardDatabase:
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    db = BlackboardDatabase(engine)
    db.create_tables()
    return db


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


def test_compose_system_prompt_excludes_cross_corpus(db: BlackboardDatabase) -> None:
    """compose_system_prompt should NOT include cross-corpus.

    The dynamic decorator handles cross-corpus in both modes now.
    The dynamic decorator handles cross-corpus in both modes now.
    """
    from pathlib import Path

    from harness_poc.app_factory import compose_system_prompt
    from harness_poc.core.config import (
        HarnessConfig,
        HarnessPaths,
        LLMConfig,
        ObservabilityConfig,
        RuntimeConfig,
    )

    related = "deverino:related"
    entries = [_make_entry(priority=0.9, summary="Related fact.")]
    db.start_session("test-session", active_corpus_key="deverino:codebase")
    db.write_map_and_mark_processed(
        related, entries, token_count=10, event_ids=["evt-1"]
    )

    config = HarnessConfig(
        project_root=Path.cwd(),
        config_path=Path.cwd() / "harness.yaml",
        paths=HarnessPaths(
            soul=Path.cwd() / "harness_poc/system_prompts/SOUL.md",
            system_tools=Path.cwd() / "harness_poc/system_tools",
            system_skills=Path.cwd() / "harness_poc/system_skills",
            project_skills=Path.cwd() / "skills",
            workflows=Path.cwd() / "workflows",
            pipelines=Path.cwd() / "pipelines",
            personas=Path.cwd() / "personas",
            react_spec=Path.cwd() / "deverino_react.acdl",
        ),
        runtime=RuntimeConfig(database_url="sqlite:///:memory:", default_container_image="python:3.14-slim"),
        llm=LLMConfig(provider="deepseek", model="deepseek-v4-flash", base_url=None),
        observability=ObservabilityConfig(logfire_enabled=False),
    )

    identity = SimpleNamespace(
        database=db,
        config_project_id="deverino",
        session_id="test-session",
    )

    prompt = compose_system_prompt(identity, config)
    # Cross-corpus should NOT be in the system prompt (decorator handles it)
    assert "Related Corpora" not in prompt
