"""Tests for list_corpora system tool — Gap 1c."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import Engine

from harness_poc.core.context_map.schema import MapEntry
from harness_poc.core.events import MapEntryReferenced
from harness_poc.core.permissions import SkillPermissions
from harness_poc.core.storage import BlackboardDatabase
from harness_poc.core.storage.blackboard_proxy import BlackboardAccessProxy
from harness_poc.core.tools import ToolContext
from harness_poc.system_tools.corpus_tools import _list_corpora


def _make_context(db: BlackboardDatabase) -> ToolContext:
    """Construct a ToolContext matching what ToolRunner injects."""
    proxy = BlackboardAccessProxy(db, SkillPermissions(blackboard="read"))
    return ToolContext(
        session_id="test-session",
        project_root=Path.cwd(),
        database=proxy,
    )


def _entry(key: str, section: str) -> MapEntry:
    now = datetime.now(tz=UTC)
    return MapEntry(
        entry_id=f"{key}-id",
        key=key,
        section=section,
        observation_type="schema",
        summary="x",
        priority=0.8,
        source_event_ids=[],
        first_seen=now,
        last_updated=now,
        materialization_count=0,
        first_seen_cycle=1,
        last_seen_cycle=1,
        token_estimate=5,
    )


def test_list_corpora_returns_structured_inventory(
    db_engine: Engine,
) -> None:
    db = BlackboardDatabase(db_engine)
    db.create_tables()
    db.write_map_and_mark_processed(
        "deverino:codebase",
        map_entries=[_entry(key="x", section="entities")],
        token_count=10, event_ids=[],
    )
    ctx = _make_context(db)
    result = _list_corpora(ctx=ctx)

    assert result == {
        "corpora": [
            {
                "key": "deverino:codebase",
                "materialized": True,
                "entry_count": 1,
                "cycle": 0,
                "has_pending_events": False,
            },
        ],
    }


def test_list_corpora_empty_database(db_engine: Engine) -> None:
    db = BlackboardDatabase(db_engine)
    db.create_tables()
    ctx = _make_context(db)
    result = _list_corpora(ctx=ctx)
    assert result == {"corpora": []}


def test_list_corpora_reports_pending_events(db_engine: Engine) -> None:
    db = BlackboardDatabase(db_engine)
    db.create_tables()
    db.write_map_and_mark_processed(
        "deverino:codebase",
        map_entries=[_entry(key="x", section="entities")],
        token_count=10, event_ids=[],
    )
    db.append_context_map_event(
        MapEntryReferenced(
            session_id="s", corpus_key="deverino:dashboard",
            entry_id="a" * 32, entry_key="y",
            section="insights", cycle_n=0, citation_context="ctx",
        ),
    )

    ctx = _make_context(db)
    result = _list_corpora(ctx=ctx)
    corpora = {c["key"]: c for c in result["corpora"]}

    assert corpora["deverino:codebase"]["has_pending_events"] is False
    assert corpora["deverino:dashboard"]["materialized"] is False
    assert corpora["deverino:dashboard"]["entry_count"] == 0
    assert corpora["deverino:dashboard"]["has_pending_events"] is True
