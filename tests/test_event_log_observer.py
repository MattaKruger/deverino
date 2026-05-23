from __future__ import annotations

import json

from sqlalchemy import Engine

from harness_poc.core.events import (
    AgentInputAdded,
    EventStore,
    LLMActionEmitted,
    SkillCompleted,
    fetch_event_log_rows,
    fetch_latest_event_log_rows,
    render_event_log_row,
)


def test_fetch_event_log_rows_filters_by_session_type_and_offset(db_engine: Engine) -> None:
    store = EventStore(db_engine)
    store.persist(AgentInputAdded(session_id="s1", user_content="hello"))
    store.persist(LLMActionEmitted(session_id="s1", model="fake", tokens_used=12))
    store.persist(LLMActionEmitted(session_id="s2", model="fake", tokens_used=99))
    store.persist(
        SkillCompleted(
            session_id="s1",
            skill_name="demo",
            status="success",
            result="ok",
        )
    )

    rows = fetch_event_log_rows(
        db_engine,
        after_id=1,
        session_id="s1",
        event_types=["LLMActionEmitted", "SkillCompleted"],
    )

    assert [row.event_type for row in rows] == ["LLMActionEmitted", "SkillCompleted"]
    assert all(row.session_id == "s1" for row in rows)


def test_fetch_event_log_rows_respects_limit(db_engine: Engine) -> None:
    store = EventStore(db_engine)
    store.persist(AgentInputAdded(session_id="s1", user_content="one"))
    store.persist(AgentInputAdded(session_id="s1", user_content="two"))

    rows = fetch_event_log_rows(db_engine, session_id="s1", limit=1)

    assert len(rows) == 1
    assert rows[0].payload["user_content"] == "one"


def test_fetch_latest_event_log_rows_returns_recent_rows_chronologically(
    db_engine: Engine,
) -> None:
    store = EventStore(db_engine)
    store.persist(AgentInputAdded(session_id="s1", user_content="one"))
    store.persist(AgentInputAdded(session_id="s1", user_content="two"))
    store.persist(AgentInputAdded(session_id="s1", user_content="three"))

    rows = fetch_latest_event_log_rows(db_engine, session_id="s1", limit=2)

    assert [row.payload["user_content"] for row in rows] == ["two", "three"]


def test_render_event_log_row_shows_pretty_payload_by_default(db_engine: Engine) -> None:
    store = EventStore(db_engine)
    store.persist(LLMActionEmitted(session_id="s1", model="fake", tokens_used=12))
    row = fetch_event_log_rows(db_engine, session_id="s1")[0]

    rendered = render_event_log_row(row)

    assert "000001" in rendered
    assert "LLMActionEmitted" in rendered
    assert "model=fake tokens=12 billable=12" in rendered
    assert "  payload:" in rendered
    assert '    "tokens_used": 12' in rendered


def test_render_event_log_row_can_hide_payload(db_engine: Engine) -> None:
    store = EventStore(db_engine)
    store.persist(LLMActionEmitted(session_id="s1", model="fake", tokens_used=12))
    row = fetch_event_log_rows(db_engine, session_id="s1")[0]

    rendered = render_event_log_row(row, include_payload=False)

    assert "LLMActionEmitted" in rendered
    assert "payload:" not in rendered


def test_render_event_log_row_json_outputs_full_payload(db_engine: Engine) -> None:
    store = EventStore(db_engine)
    store.persist(AgentInputAdded(session_id="s1", user_content="hello"))
    row = fetch_event_log_rows(db_engine, session_id="s1")[0]

    rendered = json.loads(render_event_log_row(row, json_output=True))

    assert rendered["event_type"] == "AgentInputAdded"
    assert rendered["payload"]["user_content"] == "hello"
