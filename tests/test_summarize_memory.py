# ruff: noqa: PLC0415, PLR2004
from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import Engine

from harness_poc.core.config import (
    HarnessConfig,
    HarnessPaths,
    LLMConfig,
    ObservabilityConfig,
    RuntimeConfig,
)
from harness_poc.core.database import BlackboardDatabase
from harness_poc.core.skill_runner import SkillRunner


def test_summarize_memory_requires_memory_key(db_engine: Engine) -> None:
    runner, session_id, _ = _runner(db_engine)
    with pytest.raises(ValueError, match="summarize_memory requires memory_key"):
        runner.execute_skill(
            tool_name="summarize_memory",
            arguments={},
            session_id=session_id,
        )


def test_summarize_memory_fails_when_memory_missing(db_engine: Engine) -> None:
    runner, session_id, _ = _runner(db_engine)

    result = runner.execute_skill(
        tool_name="summarize_memory",
        arguments={"memory_key": "nonexistent_key"},
        session_id=session_id,
    )
    assert result.status == "failed"
    assert "No memory found" in result.content


def test_summarize_memory_produces_summary_for_existing_memory(
    db_engine: Engine,
) -> None:
    runner, session_id, database = _runner(db_engine)
    database.write_memory(
        session_id,
        "research_key",
        {
            "topic": "PydanticAI migration",
            "findings": "run_stream stops at first text; use agent.iter() instead.",
        },
    )

    result = runner.execute_skill(
        tool_name="summarize_memory",
        arguments={"memory_key": "research_key"},
        session_id=session_id,
    )
    # Mock LLM (TestModel) produces deterministic output
    # The model returns the system prompt content since TestModel echoes
    assert result.status == "success"
    assert result.artifacts["memory_key"] == "research_key"
    assert isinstance(result.artifacts.get("summary"), str)


def test_summarize_memory_handles_string_payload(db_engine: Engine) -> None:
    runner, session_id, database = _runner(db_engine)
    database.write_memory(session_id, "string_key", "A plain text memory value.")

    result = runner.execute_skill(
        tool_name="summarize_memory",
        arguments={"memory_key": "string_key"},
        session_id=session_id,
    )
    assert result.status == "success"


def test_summarize_memory_builds_messages_with_json_payload() -> None:
    from skills.summarize_memory.skill import _build_messages

    messages = _build_messages(
        memory_key="test_key",
        payload={"data": "test value", "nested": {"key": "val"}},
    )
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert "test_key" in messages[1]["content"]
    assert "test value" in messages[1]["content"]


def test_summarize_memory_builds_messages_with_string_payload() -> None:
    from skills.summarize_memory.skill import _build_messages

    messages = _build_messages(memory_key="test_key", payload="just a string payload")
    assert "just a string payload" in messages[1]["content"]


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
            system_skills=repo_root / "harness_poc/system_skills",
            project_skills=repo_root / "skills",
            workflows=repo_root / "workflows",
            pipelines=repo_root / "pipelines",
            personas=repo_root / "personas",
        ),
        runtime=RuntimeConfig(
            database_url=engine.url.render_as_string(hide_password=False),
            default_container_image="python:3.12-slim",
        ),
        observability=ObservabilityConfig(logfire_enabled=False),
        llm=LLMConfig(provider="deepseek", model="deepseek-v4-flash", base_url=None),
    )
