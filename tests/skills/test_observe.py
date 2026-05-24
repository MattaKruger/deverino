from __future__ import annotations

from sqlalchemy import Engine

from harness_poc.core.config import HarnessConfig
from harness_poc.core.skills import SkillRunner
from harness_poc.core.storage import BlackboardDatabase

_BASE_ARGS = {
    "observation_type": "entity",
    "summary": "BlackboardDatabase owns all durable state writes",
    "detail": "Centralizing writes here keeps event ordering deterministic.",
}


def _run(
    database: BlackboardDatabase,
    config: HarnessConfig,
    session_id: str,
    **overrides: object,
) -> object:
    runner = SkillRunner(database=database, config=config)
    return runner.execute_skill(
        tool_name="observe",
        arguments={**_BASE_ARGS, **overrides},
        session_id=session_id,
    )


def test_observe_defaults_to_codebase_corpus(
    test_config: HarnessConfig, db_engine: Engine,
) -> None:
    database = BlackboardDatabase(db_engine)
    session_id = database.start_session("test")
    result = _run(database, test_config, session_id)

    assert result.status == "success"
    expected = f"{test_config.project_id}:codebase"
    assert result.artifacts["corpus_key"] == expected
    events = database.get_pending_context_map_events(expected)
    assert len(events) == 1


def test_observe_routes_to_explicit_corpus(
    test_config: HarnessConfig, db_engine: Engine,
) -> None:
    database = BlackboardDatabase(db_engine)
    session_id = database.start_session("test")
    result = _run(
        database, test_config, session_id,
        corpus_key="deverino:dashboard",
    )

    assert result.status == "success"
    assert result.artifacts["corpus_key"] == "deverino:dashboard"
    assert database.get_pending_context_map_events("deverino:dashboard")
    # Default corpus must not receive a stray event.
    assert not database.get_pending_context_map_events(
        f"{test_config.project_id}:codebase",
    )


def test_observe_rejects_malformed_corpus_key(
    test_config: HarnessConfig, db_engine: Engine,
) -> None:
    database = BlackboardDatabase(db_engine)
    session_id = database.start_session("test")
    result = _run(
        database, test_config, session_id,
        corpus_key="deverino-dashboard",  # missing the ':'
    )

    assert result.status == "failed"
    assert "expected 'project:name'" in result.content
    # No event should land in *any* corpus.
    assert not database.get_pending_context_map_events("deverino-dashboard")
    assert not database.get_pending_context_map_events(
        f"{test_config.project_id}:codebase",
    )
