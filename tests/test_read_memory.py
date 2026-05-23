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


def test_read_memory_lists_keys_when_no_key_provided(db_engine: Engine) -> None:
    runner, session_id, database = _runner(db_engine)
    database.write_memory(session_id, "key1", "value1")
    database.write_memory(session_id, "key2", {"nested": True})

    result = runner.execute_skill(tool_name="read_memory", arguments={}, session_id=session_id)
    assert result.status == "success"
    assert "key1" in result.content
    assert "key2" in result.content


def test_read_memory_returns_empty_list_when_no_memory(db_engine: Engine) -> None:
    runner, session_id, _ = _runner(db_engine)

    result = runner.execute_skill(tool_name="read_memory", arguments={}, session_id=session_id)
    assert result.status == "success"
    assert "memory_keys" in result.content


def test_read_memory_returns_payload_for_specific_key(db_engine: Engine) -> None:
    runner, session_id, database = _runner(db_engine)
    database.write_memory(session_id, "my_key", {"data": "test payload"})

    result = runner.execute_skill(
        tool_name="read_memory",
        arguments={"memory_key": "my_key"},
        session_id=session_id,
    )
    assert result.status == "success"
    assert "test payload" in result.content
    assert result.artifacts["memory_key"] == "my_key"


def test_read_memory_returns_failed_when_key_missing(db_engine: Engine) -> None:
    runner, session_id, _ = _runner(db_engine)

    result = runner.execute_skill(
        tool_name="read_memory",
        arguments={"memory_key": "nonexistent"},
        session_id=session_id,
    )
    assert result.status == "failed"
    assert "No memory found" in result.content


def test_read_memory_handles_string_payload(db_engine: Engine) -> None:
    runner, session_id, database = _runner(db_engine)
    database.write_memory(session_id, "string_key", "just a string")

    result = runner.execute_skill(
        tool_name="read_memory",
        arguments={"memory_key": "string_key"},
        session_id=session_id,
    )
    assert result.status == "success"
    assert "just a string" in result.content


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
