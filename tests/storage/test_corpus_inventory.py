"""Tests for get_all_corpus_keys — Gap 1a."""

from __future__ import annotations

from sqlalchemy import Engine

from harness_poc.app_factory import _render_corpus_inventory
from harness_poc.core.events import MapEntryReferenced
from harness_poc.core.storage import BlackboardDatabase


def test_get_all_corpus_keys_unions_materialized_and_pending(
    db_engine: Engine,
) -> None:
    db = BlackboardDatabase(db_engine)
    db.create_tables()
    db.write_map_and_mark_processed(
        "deverino:codebase",
        map_entries=[], token_count=0, event_ids=[],
    )
    db.append_context_map_event(
        MapEntryReferenced(
            session_id="s", corpus_key="deverino:dashboard",
            entry_id="a" * 32, entry_key="x",
            section="entities", cycle_n=0, citation_context="ctx",
        ),
    )
    assert db.get_all_corpus_keys() == [
        "deverino:codebase", "deverino:dashboard",
    ]


def test_get_all_corpus_keys_deduplicates_union(db_engine: Engine) -> None:
    """Corpus with both materialized map and pending events must appear once."""
    db = BlackboardDatabase(db_engine)
    db.create_tables()
    db.write_map_and_mark_processed(
        "deverino:codebase",
        map_entries=[], token_count=0, event_ids=[],
    )
    db.append_context_map_event(
        MapEntryReferenced(
            session_id="s", corpus_key="deverino:codebase",
            entry_id="a" * 32, entry_key="x",
            section="entities", cycle_n=0, citation_context="ctx",
        ),
    )
    assert db.get_all_corpus_keys() == ["deverino:codebase"]


def test_get_all_corpus_keys_empty(db_engine: Engine) -> None:
    db = BlackboardDatabase(db_engine)
    db.create_tables()
    assert db.get_all_corpus_keys() == []


# ---------------------------------------------------------------------------
# _render_corpus_inventory tests — Gap 1b
# ---------------------------------------------------------------------------


def _identity_for(database: BlackboardDatabase) -> object:
    from types import SimpleNamespace

    return SimpleNamespace(database=database)


def test_inventory_omitted_for_single_corpus(db_engine: Engine) -> None:
    db = BlackboardDatabase(db_engine)
    db.create_tables()
    db.write_map_and_mark_processed(
        "deverino:codebase",
        map_entries=[], token_count=0, event_ids=[],
    )
    assert _render_corpus_inventory(_identity_for(db), "deverino:codebase") == ""  # type: ignore[arg-type]


def test_inventory_marks_active(db_engine: Engine) -> None:
    db = BlackboardDatabase(db_engine)
    db.create_tables()
    db.write_map_and_mark_processed(
        "deverino:codebase",
        map_entries=[], token_count=0, event_ids=[],
    )
    db.write_map_and_mark_processed(
        "deverino:dashboard",
        map_entries=[], token_count=0, event_ids=[],
    )
    body = _render_corpus_inventory(_identity_for(db), "deverino:dashboard")  # type: ignore[arg-type]
    assert "deverino:dashboard (primary)" in body
    assert "deverino:codebase" in body
    assert "deverino:codebase (primary)" not in body


def test_inventory_omitted_for_empty_database(db_engine: Engine) -> None:
    db = BlackboardDatabase(db_engine)
    db.create_tables()
    assert _render_corpus_inventory(_identity_for(db), "deverino:codebase") == ""  # type: ignore[arg-type]
