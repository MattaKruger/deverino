from __future__ import annotations

from unittest.mock import MagicMock

from sqlalchemy import Engine

from harness_poc.core.event_bus import EventBus
from harness_poc.core.event_store import EventStore
from harness_poc.core.events import AgentStarted, SkillCalled
from tests.helpers import RecordingEventBus

# --- RecordingEventBus ---


def test_recording_bus_stores_published_events() -> None:
    bus = RecordingEventBus()
    event = AgentStarted(session_id="s1", goal="test goal")
    bus.publish(event)
    assert len(bus.events) == 1
    assert bus.events[0] is event


def test_recording_bus_filters_by_session() -> None:
    bus = RecordingEventBus()
    bus.publish(AgentStarted(session_id="s1", goal="g"))
    bus.publish(AgentStarted(session_id="s2", goal="g"))
    events = bus.get_recent_events("s1")
    assert len(events) == 1
    assert events[0].session_id == "s1"


def test_recording_bus_filters_by_event_type() -> None:
    bus = RecordingEventBus()
    bus.publish(AgentStarted(session_id="s1", goal="g"))
    bus.publish(SkillCalled(session_id="s1", tool_name="foo", arguments={}))
    events = bus.get_recent_events("s1", event_types=[SkillCalled])
    assert len(events) == 1
    assert isinstance(events[0], SkillCalled)


def test_recording_bus_respects_limit() -> None:
    bus = RecordingEventBus()
    num_events = 5
    limit = 3
    for i in range(num_events):
        bus.publish(SkillCalled(session_id="s1", tool_name=f"s{i}", arguments={}))
    events = bus.get_recent_events("s1", limit=limit)
    assert len(events) == limit
    assert isinstance(events[-1], SkillCalled)
    assert events[-1].tool_name == "s4"


# --- EventBus with real EventStore ---


def test_event_bus_publish_dispatches_to_subscriber(db_engine: Engine) -> None:
    bus = EventBus(EventStore(db_engine))
    handler = MagicMock()
    bus.subscribe(SkillCalled, handler)
    event = SkillCalled(session_id="s1", tool_name="foo", arguments={})
    bus.publish(event)
    handler.assert_called_once_with(event)


def test_event_bus_bad_handler_does_not_stop_other_handlers(db_engine: Engine) -> None:
    bus = EventBus(EventStore(db_engine))
    results: list[str] = []
    error_msg = "handler failure"

    def bad_handler(_event: SkillCalled) -> None:
        raise RuntimeError(error_msg)

    def good_handler(event: SkillCalled) -> None:
        results.append(event.tool_name)

    bus.subscribe(SkillCalled, bad_handler)
    bus.subscribe(SkillCalled, good_handler)
    bus.publish(SkillCalled(session_id="s1", tool_name="foo", arguments={}))
    assert results == ["foo"]


def test_event_bus_get_recent_events_reads_from_store(db_engine: Engine) -> None:
    bus = EventBus(EventStore(db_engine))
    bus.publish(AgentStarted(session_id="s1", goal="g"))
    bus.publish(SkillCalled(session_id="s1", tool_name="foo", arguments={}))
    events = bus.get_recent_events("s1")
    expected_count = 2
    assert len(events) == expected_count
    assert isinstance(events[0], AgentStarted)
    assert isinstance(events[1], SkillCalled)
