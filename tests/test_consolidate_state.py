from __future__ import annotations

from pathlib import Path

from harness_poc.core.config import HarnessConfig, HarnessPaths, RuntimeConfig
from harness_poc.core.database import BlackboardDatabase
from harness_poc.core.skill_runner import SkillRunner


def test_consolidate_state_preview_returns_session_state(tmp_path: Path) -> None:
    config = _test_config(tmp_path)
    database = BlackboardDatabase(config.runtime.database_path)
    database.create_tables()
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


def test_consolidate_state_approve_updates_project_state(tmp_path: Path) -> None:
    config = _test_config(tmp_path)
    database = BlackboardDatabase(config.runtime.database_path)
    database.create_tables()
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


def _test_config(tmp_path: Path) -> HarnessConfig:
    project_root = Path.cwd()
    return HarnessConfig(
        project_root=project_root,
        config_path=project_root / "harness.yaml",
        paths=HarnessPaths(
            soul=project_root / "harness_poc/system_prompts/SOUL.md",
            system_skills=project_root / "harness_poc/system_skills",
            project_skills=project_root / "skills",
            workflows=project_root / "workflows",
            personas=project_root / "personas",
        ),
        runtime=RuntimeConfig(
            database_path=tmp_path / "blackboard.db",
            default_container_image="python:3.12-slim",
        ),
    )
