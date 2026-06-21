from __future__ import annotations

from sqlalchemy import Engine
from sqlmodel import Session

from harness_poc.core.events import AgentStarted, EventStore, SkillCalled, SkillCompleted
from harness_poc.core.storage import DbStateEvent


def _make_store(engine: Engine) -> EventStore:
    return EventStore(engine)


def test_persist_and_retrieve_single_event(db_engine: Engine) -> None:
    store = _make_store(db_engine)
    event = SkillCalled(session_id="s1", tool_name="read_memory", arguments={"key": "x"})
    store.persist(event)
    events = store.get_recent_events("s1")
    assert len(events) == 1
    assert isinstance(events[0], SkillCalled)
    assert events[0].id == 1
    assert events[0].tool_name == "read_memory"
    assert events[0].arguments == {"key": "x"}


def test_get_recent_events_respects_limit(db_engine: Engine) -> None:
    store = _make_store(db_engine)
    limit = 3
    for i in range(5):
        store.persist(SkillCalled(session_id="s1", tool_name=f"skill_{i}", arguments={}))
    events = store.get_recent_events("s1", limit=limit)
    assert len(events) == limit
    assert isinstance(events[-1], SkillCalled)
    assert events[-1].tool_name == "skill_4"  # most recent last


def test_get_recent_events_type_filter(db_engine: Engine) -> None:
    store = _make_store(db_engine)
    expected_count = 2
    store.persist(AgentStarted(session_id="s1", goal="g"))
    store.persist(SkillCalled(session_id="s1", tool_name="foo", arguments={}))
    store.persist(SkillCompleted(session_id="s1", tool_name="foo", status="success", content="ok"))
    events = store.get_recent_events("s1", event_types=[SkillCalled, SkillCompleted])
    assert len(events) == expected_count
    assert all(isinstance(e, (SkillCalled, SkillCompleted)) for e in events)


def test_get_recent_events_returns_chronological_order(db_engine: Engine) -> None:
    store = _make_store(db_engine)
    store.persist(SkillCalled(session_id="s1", tool_name="first", arguments={}))
    store.persist(SkillCalled(session_id="s1", tool_name="second", arguments={}))
    events = store.get_recent_events("s1")
    assert isinstance(events[0], SkillCalled)
    assert isinstance(events[1], SkillCalled)
    assert events[0].tool_name == "first"
    assert events[1].tool_name == "second"


def test_skips_malformed_event_payload_and_continues(db_engine: Engine) -> None:
    from datetime import UTC, datetime

    store = _make_store(db_engine)
    # Inject a row with a valid event_type but missing required fields in the inner payload
    with Session(db_engine) as session:
        session.add(
            DbStateEvent(
                scope="session",
                scope_id="s2",
                event_type="SkillCalled",
                payload={"event_type": "SkillCalled", "payload": {"session_id": "s2"}},
                created_at=datetime.now(tz=UTC).isoformat(timespec="seconds"),
            )
        )
        session.commit()

    store.persist(SkillCalled(session_id="s2", tool_name="good_skill", arguments={}))
    events = store.get_recent_events("s2")
    assert len(events) == 1
    assert isinstance(events[0], SkillCalled)
    assert events[0].tool_name == "good_skill"


def test_skips_unrecognized_event_type_and_continues(db_engine: Engine) -> None:
    store = _make_store(db_engine)
    # Inject a legacy row with unknown event_type directly via SQLModel
    from datetime import UTC, datetime

    with Session(db_engine) as session:
        session.add(
            DbStateEvent(
                scope="session",
                scope_id="s1",
                event_type="OldLegacyEvent",
                payload={"tool_name": "x"},
                created_at=datetime.now(tz=UTC).isoformat(timespec="seconds"),
            )
        )
        session.commit()

    store.persist(SkillCalled(session_id="s1", tool_name="bar", arguments={}))
    events = store.get_recent_events("s1")
    assert len(events) == 1
    assert isinstance(events[0], SkillCalled)
    assert events[0].tool_name == "bar"
