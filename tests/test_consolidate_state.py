from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine

from harness_poc.core.config import (
    HarnessConfig,
    HarnessPaths,
    LLMConfig,
    ObservabilityConfig,
    RuntimeConfig,
)
from harness_poc.core.skill_runner import SkillRunner
from harness_poc.core.storage import BlackboardDatabase


def test_consolidate_state_preview_returns_session_state(db_engine: Engine) -> None:
    config = _test_config(db_engine)
    database = BlackboardDatabase(db_engine)
    session_id = database.start_session("test")
    database.ensure_session_state(session_id)
    database.append_session_state(
        session_id=session_id,
        section="notes",
        text="Preview this note.",
    )

    runner = SkillRunner(database=database, config=config)
    result = runner.execute_skill(
        tool_name="consolidate_state",
        arguments={"mode": "preview"},
        session_id=session_id,
    )

    assert result.status == "success"
    assert "Preview this note." in result.content
    assert result.artifacts["proposal_status"] == "not_created"


def test_consolidate_state_approve_updates_project_state(db_engine: Engine) -> None:
    config = _test_config(db_engine)
    database = BlackboardDatabase(db_engine)
    session_id = database.start_session("test")
    database.ensure_session_state(session_id)
    database.append_session_state(
        session_id=session_id,
        section="decisions",
        text="Approve this decision.",
    )

    runner = SkillRunner(database=database, config=config)
    result = runner.execute_skill(
        tool_name="consolidate_state",
        arguments={"mode": "approve"},
        session_id=session_id,
    )

    project_state = database.ensure_project_state()
    assert result.status == "success"
    assert result.artifacts["proposal_status"] == "approved"
    assert "Approve this decision." in project_state.decisions


def _test_config(engine: Engine) -> HarnessConfig:
    project_root = Path.cwd()
    return HarnessConfig(
        project_root=project_root,
        config_path=project_root / "harness.yaml",
        paths=HarnessPaths(
            soul=project_root / "harness_poc/system_prompts/SOUL.md",
            system_tools=project_root / "harness_poc/system_tools",
            system_skills=project_root / "harness_poc/system_skills",
            project_skills=project_root / "skills",
            workflows=project_root / "workflows",
            pipelines=project_root / "pipelines",
            personas=project_root / "personas",
        ),
        runtime=RuntimeConfig(
            database_url=engine.url.render_as_string(hide_password=False),
            default_container_image="python:3.14-slim",
        ),
        observability=ObservabilityConfig(logfire_enabled=False),
        llm=LLMConfig(provider="deepseek", model="deepseek-v4-flash", base_url=None),
    )
