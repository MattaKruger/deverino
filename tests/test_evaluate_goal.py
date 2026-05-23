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
from harness_poc.core.skills import SkillRunner
from harness_poc.core.storage import BlackboardDatabase


def test_evaluate_goal_echoes_inputs_when_complete(db_engine: Engine) -> None:
    runner, session_id, _ = _runner(db_engine)

    result = runner.execute_skill(
        tool_name="evaluate_goal",
        arguments={
            "is_complete": True,
            "reasoning": "All tasks done.",
            "final_answer": "The answer is 42.",
        },
        session_id=session_id,
    )
    assert result.status == "success"
    assert "complete=True" in result.content
    assert "All tasks done" in result.content
    assert result.artifacts["is_complete"] is True
    assert result.artifacts["reasoning"] == "All tasks done."
    assert result.artifacts["final_answer"] == "The answer is 42."


def test_evaluate_goal_echoes_inputs_when_incomplete(db_engine: Engine) -> None:
    runner, session_id, _ = _runner(db_engine)

    result = runner.execute_skill(
        tool_name="evaluate_goal",
        arguments={
            "is_complete": False,
            "reasoning": "Still working on the task.",
        },
        session_id=session_id,
    )
    assert result.status == "success"
    assert "complete=False" in result.content
    assert "Still working on the task" in result.content
    assert result.artifacts["is_complete"] is False


def test_evaluate_goal_handles_defaults(db_engine: Engine) -> None:
    runner, session_id, _ = _runner(db_engine)

    result = runner.execute_skill(
        tool_name="evaluate_goal",
        arguments={"is_complete": False, "reasoning": ""},
        session_id=session_id,
    )
    assert result.status == "success"
    assert result.artifacts["is_complete"] is False
    assert result.artifacts["reasoning"] == ""


def _runner(engine: Engine) -> tuple[SkillRunner, str, BlackboardDatabase]:
    config = _test_config(engine)
    database = BlackboardDatabase(engine)
    session_id = database.start_session("test")
    return SkillRunner(database=database, config=config), session_id, database


def _test_config(engine: Engine) -> HarnessConfig:
    repo_root = Path.cwd()
    return HarnessConfig(
        project_root=repo_root,
        config_path=repo_root / "harness.yaml",
        paths=HarnessPaths(
            soul=repo_root / "harness_poc/system_prompts/SOUL.md",
            system_tools=repo_root / "harness_poc/system_tools",
            system_skills=repo_root / "harness_poc/system_skills",
            project_skills=repo_root / "skills",
            workflows=repo_root / "workflows",
            pipelines=repo_root / "pipelines",
            personas=repo_root / "personas",
        ),
        runtime=RuntimeConfig(
            database_url=engine.url.render_as_string(hide_password=False),
            default_container_image="python:3.14-slim",
        ),
        observability=ObservabilityConfig(logfire_enabled=False),
        llm=LLMConfig(provider="deepseek", model="deepseek-v4-flash", base_url=None),
    )
