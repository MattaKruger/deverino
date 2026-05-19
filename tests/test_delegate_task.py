from __future__ import annotations

from pathlib import Path

import pytest

from harness_poc.core.config import (
    HarnessConfig,
    HarnessPaths,
    LLMConfig,
    ObservabilityConfig,
    RuntimeConfig,
)
from harness_poc.core.database import BlackboardDatabase
from harness_poc.core.skill_runner import SkillRunner


def test_delegate_task_uses_pydanticai_fallback_and_writes_memory(
    tmp_path: Path,
) -> None:
    runner, database, session_id = _runner(tmp_path)

    result = runner.execute_skill(
        tool_name="delegate_task",
        arguments={
            "persona": "web_researcher",
            "objective": "Explain PydanticAI migration tradeoffs",
            "memory_key": "delegated_result",
            "context": "Current harness uses dynamic skills.",
            "use_mock": True,
        },
        session_id=session_id,
    )

    memory = database.read_memory(session_id, "delegated_result")
    assert result.status == "success"
    assert isinstance(memory, dict)
    assert memory["status"] == "completed"
    assert "Explain PydanticAI migration tradeoffs" in memory["summary"]
    assert memory["artifacts"]["persona"] == "web_researcher"
    assert memory["artifacts"]["objective"] == "Explain PydanticAI migration tradeoffs"
    assert memory["artifacts"]["received_context"] == "Current harness uses dynamic skills."
    assert memory["artifacts"]["model_output"]["status"] == "completed"


def test_delegate_task_accepts_template_name_alias(tmp_path: Path) -> None:
    runner, database, session_id = _runner(tmp_path)

    result = runner.execute_skill(
        tool_name="delegate_task",
        arguments={
            "template_name": "web_researcher",
            "objective": "Summarize adapter design",
            "use_mock": True,
        },
        session_id=session_id,
    )

    memory = database.read_memory(session_id, "web_researcher_result")
    assert result.status == "success"
    assert isinstance(memory, dict)
    assert memory["artifacts"]["persona"] == "web_researcher"


def test_delegate_task_streams_summary_chunks(tmp_path: Path) -> None:
    runner, _database, session_id = _runner(tmp_path)
    chunks: list[str] = []

    result = runner.execute_skill(
        tool_name="delegate_task",
        arguments={
            "persona": "web_researcher",
            "objective": "Stream delegated research",
            "use_mock": True,
        },
        session_id=session_id,
        on_text=chunks.append,
    )

    assert result.status == "success"
    assert "".join(chunks)
    assert "Stream delegated research" in "".join(chunks)


def test_delegate_task_requires_persona_and_objective(tmp_path: Path) -> None:
    runner, _database, session_id = _runner(tmp_path)

    with pytest.raises(ValueError, match="delegate_task requires objective"):
        runner.execute_skill(
            tool_name="delegate_task",
            arguments={"persona": "web_researcher"},
            session_id=session_id,
        )


def _runner(tmp_path: Path) -> tuple[SkillRunner, BlackboardDatabase, str]:
    config = _test_config(tmp_path)
    database = BlackboardDatabase(config.runtime.database_path)
    database.create_tables()
    session_id = database.start_session("Delegate task test session.")
    return SkillRunner(database=database, config=config), database, session_id


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
            pipelines=project_root / "pipelines",
            personas=project_root / "personas",
        ),
        runtime=RuntimeConfig(
            database_path=tmp_path / "blackboard.db",
            default_container_image="python:3.12-slim",
        ),
        observability=ObservabilityConfig(logfire_enabled=False),
        llm=LLMConfig(provider="deepseek", model="deepseek-v4-flash", base_url=None),
    )
