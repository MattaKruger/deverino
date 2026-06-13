from __future__ import annotations

from sqlalchemy import Engine

from harness_poc.core.events import (
    AgentStarted,
    EntityReferenced,
    EventStore,
    LLMActionEmitted,
    SkillCalled,
    SkillCompleted,
    StreamPaused,
)
from harness_poc.core.observability import (
    fetch_dashboard_snapshot,
    fetch_session_events,
    fetch_session_ids,
    snapshot_to_dict,
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
    from datetime import UTC, datetime

    from harness_poc.core.context_map.schema import MapEntry

    database.write_map_and_mark_processed(
        corpus_key="deverino:default",
        map_entries=[
            MapEntry(
                entry_id="e1",
                key="test-key",
                section="context_understanding",
                observation_type="entity",
                summary="test summary",
                priority=0.5,
                source_event_ids=[],
                first_seen=datetime.now(tz=UTC),
                last_updated=datetime.now(tz=UTC),
                materialization_count=1,
                first_seen_cycle=1,
                last_seen_cycle=1,
                token_estimate=5,
            )
        ],
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


def test_fetch_session_ids_returns_recent_sessions(db_engine: Engine) -> None:
    from datetime import UTC, datetime

    from sqlmodel import Session

    from harness_poc.core.storage.models import DbSession

    now = datetime.now(tz=UTC).isoformat()
    with Session(db_engine) as s:
        s.add(DbSession(
            session_id="sess-aaa",
            global_objective="Find the answer",
            status="active",
            created_at=now,
        ))
        s.add(DbSession(
            session_id="sess-bbb",
            global_objective="Do another thing",
            status="active",
            created_at=now,
        ))
        s.commit()

    store = EventStore(db_engine)
    store.persist(
        LLMActionEmitted(
            session_id="sess-aaa", model="fake", tokens_used=5,
            input_tokens=3, output_tokens=2,
        )
    )

    results = fetch_session_ids(db_engine, limit=10)

    ids = [r[0] for r in results]
    assert "sess-aaa" in ids
    assert "sess-bbb" in ids
    # label contains objective and session suffix
    labels = {r[0]: r[1] for r in results}
    assert "Find the answer" in labels["sess-aaa"]
    assert "sess-aaa"[-8:] in labels["sess-aaa"]


def test_fetch_session_events_returns_ordered_events_with_time_delta(db_engine: Engine) -> None:
    store = EventStore(db_engine)
    store.persist(AgentStarted(session_id="sess-xyz", goal="Run a test"))
    store.persist(SkillCalled(session_id="sess-xyz", tool_name="search_documents"))
    store.persist(
        SkillCompleted(
            session_id="sess-xyz",
            tool_name="search_documents",
            status="success",
            content="some result",
        )
    )
    store.persist(
        LLMActionEmitted(
            session_id="sess-xyz",
            model="fake",
            tokens_used=20,
            input_tokens=15,
            output_tokens=5,
        )
    )
    store.persist(StreamPaused(session_id="sess-xyz", reason="budget"))

    rows = fetch_session_events(db_engine, "sess-xyz")

    assert len(rows) == 5
    assert rows[0].event_type == "AgentStarted"
    assert rows[0].time_delta == 0.0
    # all subsequent time_deltas are >= 0
    assert all(r.time_delta >= 0.0 for r in rows)
    # LLMActionEmitted row has tokens_used populated
    llm_rows = [r for r in rows if r.event_type == "LLMActionEmitted"]
    assert llm_rows[0].tokens_used == 20
    # SkillCompleted has content_preview
    skill_rows = [r for r in rows if r.event_type == "SkillCompleted"]
    assert "some result" in skill_rows[0].content_preview
    # unknown session returns empty list
    assert fetch_session_events(db_engine, "no-such-session") == []


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
