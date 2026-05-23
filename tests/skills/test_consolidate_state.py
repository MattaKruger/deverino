from __future__ import annotations

from sqlalchemy import Engine

from harness_poc.core.config import HarnessConfig
from harness_poc.core.skills import SkillRunner
from harness_poc.core.storage import BlackboardDatabase


def test_consolidate_state_preview_returns_session_state(
    test_config: HarnessConfig, db_engine: Engine,
) -> None:
    database = BlackboardDatabase(db_engine)
    session_id = database.start_session("test")
    database.ensure_session_state(session_id)
    database.append_session_state(
        session_id=session_id,
        section="notes",
        text="Preview this note.",
    )

    runner = SkillRunner(database=database, config=test_config)
    result = runner.execute_skill(
        tool_name="consolidate_state",
        arguments={"mode": "preview"},
        session_id=session_id,
    )

    assert result.status == "success"
    assert "Preview this note." in result.content
    assert result.artifacts["proposal_status"] == "not_created"


def test_consolidate_state_approve_updates_project_state(
    test_config: HarnessConfig, db_engine: Engine,
) -> None:
    database = BlackboardDatabase(db_engine)
    session_id = database.start_session("test")
    database.ensure_session_state(session_id)
    database.append_session_state(
        session_id=session_id,
        section="decisions",
        text="Approve this decision.",
    )

    runner = SkillRunner(database=database, config=test_config)
    result = runner.execute_skill(
        tool_name="consolidate_state",
        arguments={"mode": "approve"},
        session_id=session_id,
    )

    project_state = database.ensure_project_state()
    assert result.status == "success"
    assert result.artifacts["proposal_status"] == "approved"
    assert "Approve this decision." in project_state.decisions
