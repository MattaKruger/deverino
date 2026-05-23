from __future__ import annotations

from sqlalchemy import Engine

from harness_poc.core.dashboard import fetch_dashboard_snapshot, snapshot_to_dict
from harness_poc.core.events import (
    AgentStarted,
    EntityReferenced,
    EventStore,
    LLMActionEmitted,
    SkillCalled,
    SkillCompleted,
    StreamPaused,
)
from harness_poc.core.storage import BlackboardDatabase


def test_dashboard_snapshot_rolls_up_agent_events(db_engine: Engine) -> None:
    store = EventStore(db_engine)
    store.persist(AgentStarted(session_id="s1", goal="Find useful dashboard views"))
    store.persist(SkillCalled(session_id="s1", tool_name="search_documents"))
    store.persist(
        SkillCompleted(
            session_id="s1",
            tool_name="search_documents",
            status="success",
            content="ok",
        )
    )
    store.persist(
        SkillCompleted(
            session_id="s1",
            tool_name="execute_python",
            status="failed",
            content="boom",
        )
    )
    store.persist(
        LLMActionEmitted(
            session_id="s1",
            model="fake",
            tokens_used=30,
            input_tokens=20,
            output_tokens=10,
        )
    )
    store.persist(
        LLMActionEmitted(
            session_id="s1",
            model="fake-small",
            tokens_used=12,
            input_tokens=8,
            output_tokens=4,
        )
    )
    store.persist(
        LLMActionEmitted(
            session_id="s2",
            model="fake",
            tokens_used=7,
            input_tokens=5,
            output_tokens=2,
        )
    )
    store.persist(StreamPaused(session_id="s2", reason="budget_exhausted"))

    database = BlackboardDatabase(db_engine)
    database.append_context_map_event(
        EntityReferenced(
            session_id="s1",
            corpus_key="deverino:default",
            entity_name="state_events",
            entity_type="table",
            context="dashboard reads event rows",
        )
    )
    database.write_map_and_mark_processed(
        corpus_key="deverino:default",
        map_json={"context_understanding": []},
        token_count=5,
        event_ids=[],
    )

    snapshot = fetch_dashboard_snapshot(db_engine)

    assert snapshot.summary.total_sessions == 2
    assert snapshot.summary.total_tokens == 49
    assert snapshot.summary.skill_calls == 1
    assert snapshot.summary.skill_failures == 1
    assert snapshot.summary.context_pending == 1
    assert [row.skill_name for row in snapshot.skills] == [
        "execute_python",
        "search_documents",
    ]
    assert snapshot.skills[0].failures == 1
    assert snapshot.recent_failures[0].event_type == "StreamPaused"
    assert snapshot.token_buckets[0].input_tokens == 33
    assert snapshot.context_maps[0].corpus_key == "deverino:default"
    assert snapshot.context_maps[0].pending_events == 1
    assert snapshot.session_activity[0].session_id == "s2"
    assert snapshot.session_activity[0].status == "paused"
    assert snapshot.session_activity[1].session_id == "s1"
    assert snapshot.session_activity[1].total_tokens == 42
    assert snapshot.session_activity[1].skill_failures == 1
    assert snapshot.session_activity[1].goal == "Find useful dashboard views"
    assert [(row.model, row.tokens) for row in snapshot.model_token_usage] == [
        ("fake", 37),
        ("fake-small", 12),
    ]
    assert snapshot.session_token_usage[0].session_id == "s1"
    assert snapshot.session_token_usage[0].models == "fake, fake-small"
    assert snapshot.session_token_usage[0].tokens == 42


def test_snapshot_to_dict_handles_slot_dataclasses(db_engine: Engine) -> None:
    snapshot = fetch_dashboard_snapshot(db_engine)

    assert snapshot_to_dict(snapshot)["summary"] == {
        "total_sessions": 0,
        "total_events": 0,
        "total_tokens": 0,
        "skill_calls": 0,
        "skill_failures": 0,
        "context_pending": 0,
    }
    assert snapshot_to_dict(snapshot)["session_activity"] == []
    assert snapshot_to_dict(snapshot)["model_token_usage"] == []
    assert snapshot_to_dict(snapshot)["session_token_usage"] == []
