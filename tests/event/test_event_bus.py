from __future__ import annotations

from unittest.mock import MagicMock

from sqlalchemy import Engine

from harness_poc.core.events import AgentStarted, EventBus, EventStore, SkillCalled

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
