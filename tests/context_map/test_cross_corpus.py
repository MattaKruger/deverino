"""Tests for _render_cross_corpus — Track B §4.3 cross-corpus enrichment rendering."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from harness_poc.app_factory import _render_cross_corpus
from harness_poc.core.context_map.config import CartographerConfig
from harness_poc.core.context_map.schema import MapEntry
from harness_poc.core.storage.database import BlackboardDatabase


@pytest.fixture
def db() -> BlackboardDatabase:
    return BlackboardDatabase.from_url("sqlite:///:memory:")


def _make_entry(*, priority: float = 0.8, section: str = "domain_constants") -> MapEntry:
    now = datetime.now(tz=UTC)
    return MapEntry(
        entry_id=str(uuid4()),
        key=f"k-{uuid4().hex[:6]}",
        section=section,
        observation_type="schema",
        summary="Some related-corpus fact.",
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
    enabled: bool,
    related: dict[str, list[str]] | None = None,
    max_entries: int = 16,
    min_priority: float = 0.7,
) -> object:
    return SimpleNamespace(
        cartographer=CartographerConfig(
            cross_corpus_enabled=enabled,
            cross_corpus_related_corpora=related or {},
            cross_corpus_max_entries=max_entries,
            cross_corpus_min_priority=min_priority,
        ),
    )


def _identity_for(database: BlackboardDatabase) -> object:
    return SimpleNamespace(database=database)


# ---------------------------------------------------------------------------
# Disabled / empty cases
# ---------------------------------------------------------------------------


def test_disabled_returns_empty(db: BlackboardDatabase) -> None:
    active = "deverino:codebase"
    related = "other:codebase"
    db.write_map_and_mark_processed(related, [_make_entry()], 10, [])

    config = _make_config(enabled=False, related={active: [related]})
    out = _render_cross_corpus(_identity_for(db), config, active)

    assert out == ""


def test_no_adjacency_returns_empty(db: BlackboardDatabase) -> None:
    active = "deverino:codebase"
    related = "other:codebase"
    db.write_map_and_mark_processed(related, [_make_entry()], 10, [])

    config = _make_config(enabled=True, related={})  # no adjacency for active
    out = _render_cross_corpus(_identity_for(db), config, active)

    assert out == ""


def test_adjacency_with_no_persisted_maps_returns_empty(db: BlackboardDatabase) -> None:
    active = "deverino:codebase"

    config = _make_config(enabled=True, related={active: ["nonexistent:codebase"]})
    out = _render_cross_corpus(_identity_for(db), config, active)

    assert out == ""


# ---------------------------------------------------------------------------
# Rendering with content
# ---------------------------------------------------------------------------


def test_renders_corpus_header_and_entries(db: BlackboardDatabase) -> None:
    active = "deverino:codebase"
    related = "other:codebase"
    entries = [_make_entry(priority=0.9), _make_entry(priority=0.8)]
    db.write_map_and_mark_processed(related, entries, 20, [])
    db.get_and_bump_cycle(related)

    config = _make_config(enabled=True, related={active: [related]})
    out = _render_cross_corpus(_identity_for(db), config, active)

    assert "# Related Corpora" in out
    assert f"## {related}" in out
    assert "cycle" in out
    assert "[entry:" in out


def test_respects_min_priority(db: BlackboardDatabase) -> None:
    active = "deverino:codebase"
    related = "other:codebase"
    entries = [_make_entry(priority=0.5), _make_entry(priority=0.9)]
    db.write_map_and_mark_processed(related, entries, 20, [])
    db.get_and_bump_cycle(related)

    config = _make_config(enabled=True, related={active: [related]}, min_priority=0.7)
    out = _render_cross_corpus(_identity_for(db), config, active)

    assert "(p=0.90)" in out
    assert "(p=0.50)" not in out


def test_respects_max_cross_entries(db: BlackboardDatabase) -> None:
    active = "deverino:codebase"
    related = "other:codebase"
    entries = [_make_entry(priority=0.9) for _ in range(30)]
    db.write_map_and_mark_processed(related, entries, 300, [])
    db.get_and_bump_cycle(related)

    config = _make_config(enabled=True, related={active: [related]}, max_entries=5)
    out = _render_cross_corpus(_identity_for(db), config, active)

    # One header line + 5 entry lines for this single related corpus
    entry_lines = [line for line in out.splitlines() if line.lstrip().startswith("- [entry:")]
    assert len(entry_lines) == 5


def test_returns_empty_when_all_entries_filtered_out(db: BlackboardDatabase) -> None:
    active = "deverino:codebase"
    related = "other:codebase"
    entries = [_make_entry(priority=0.3), _make_entry(priority=0.4)]
    db.write_map_and_mark_processed(related, entries, 20, [])
    db.get_and_bump_cycle(related)

    config = _make_config(enabled=True, related={active: [related]}, min_priority=0.7)
    out = _render_cross_corpus(_identity_for(db), config, active)

    assert out == ""


def test_multiple_related_corpora_both_rendered(db: BlackboardDatabase) -> None:
    active = "deverino:codebase"
    related_a = "other_a:codebase"
    related_b = "other_b:codebase"

    db.write_map_and_mark_processed(related_a, [_make_entry(priority=0.9)], 10, [])
    db.write_map_and_mark_processed(related_b, [_make_entry(priority=0.9)], 10, [])
    db.get_and_bump_cycle(related_a)
    db.get_and_bump_cycle(related_b)

    config = _make_config(enabled=True, related={active: [related_a, related_b]})
    out = _render_cross_corpus(_identity_for(db), config, active)

    assert f"## {related_a}" in out
    assert f"## {related_b}" in out
