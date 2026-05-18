from __future__ import annotations

import sqlite3
import tempfile

from harness_poc.core.event_store import EventStore
from harness_poc.core.events import AgentStarted, SkillCalled, SkillCompleted


def _make_store() -> EventStore:
    """EventStore backed by a temp SQLite file with the state_events table."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        db_path = tf.name
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS state_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scope TEXT NOT NULL,
            scope_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            payload TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()
    return EventStore(db_path)


def test_persist_and_retrieve_single_event() -> None:
    store = _make_store()
    event = SkillCalled(session_id="s1", tool_name="read_memory", arguments={"key": "x"})
    store.persist(event)
    events = store.get_recent_events("s1")
    assert len(events) == 1
    assert isinstance(events[0], SkillCalled)
    assert events[0].tool_name == "read_memory"
    assert events[0].arguments == {"key": "x"}


def test_get_recent_events_respects_limit() -> None:
    store = _make_store()
    limit = 3
    for i in range(5):
        store.persist(SkillCalled(session_id="s1", tool_name=f"skill_{i}", arguments={}))
    events = store.get_recent_events("s1", limit=limit)
    assert len(events) == limit
    assert isinstance(events[-1], SkillCalled)
    assert events[-1].tool_name == "skill_4"  # most recent last


def test_get_recent_events_type_filter() -> None:
    store = _make_store()
    expected_count = 2
    store.persist(AgentStarted(session_id="s1", goal="g"))
    store.persist(SkillCalled(session_id="s1", tool_name="foo", arguments={}))
    store.persist(SkillCompleted(session_id="s1", tool_name="foo", status="success", content="ok"))
    events = store.get_recent_events("s1", event_types=[SkillCalled, SkillCompleted])
    assert len(events) == expected_count
    assert all(isinstance(e, (SkillCalled, SkillCompleted)) for e in events)


def test_get_recent_events_returns_chronological_order() -> None:
    store = _make_store()
    store.persist(SkillCalled(session_id="s1", tool_name="first", arguments={}))
    store.persist(SkillCalled(session_id="s1", tool_name="second", arguments={}))
    events = store.get_recent_events("s1")
    assert isinstance(events[0], SkillCalled)
    assert isinstance(events[1], SkillCalled)
    assert events[0].tool_name == "first"
    assert events[1].tool_name == "second"


def test_skips_unrecognized_event_type_and_continues() -> None:
    store = _make_store()
    # Inject a legacy row directly
    conn = sqlite3.connect(store.database_path)
    conn.execute(
        "INSERT INTO state_events (scope, scope_id, event_type, payload, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        ("session", "s1", "OldLegacyEvent", '{"tool_name": "x"}', "2026-01-01T00:00:00"),
    )
    conn.commit()
    conn.close()
    store.persist(SkillCalled(session_id="s1", tool_name="bar", arguments={}))
    events = store.get_recent_events("s1")
    assert len(events) == 1
    assert isinstance(events[0], SkillCalled)
    assert events[0].tool_name == "bar"
