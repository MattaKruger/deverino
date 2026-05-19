from __future__ import annotations

import json
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


def test_review_work_requires_memory_key(tmp_path: Path) -> None:
    runner, session_id, _ = _runner(tmp_path)
    with pytest.raises(ValueError, match="review_work requires memory_key"):
        runner.execute_skill(
            tool_name="review_work",
            arguments={"objective": "Test objective"},
            session_id=session_id,
        )


def test_review_work_fails_when_memory_missing(tmp_path: Path) -> None:
    runner, session_id, database = _runner(tmp_path)

    result = runner.execute_skill(
        tool_name="review_work",
        arguments={
            "objective": "Check missing result",
            "memory_key": "nonexistent_key",
        },
        session_id=session_id,
    )
    assert result.status == "failed"
    review = json.loads(result.content)
    assert review["verdict"] == "fail"
    assert "No result was found" in review["summary"]


def test_review_work_passes_when_memory_exists(tmp_path: Path) -> None:
    runner, session_id, database = _runner(tmp_path)
    database.write_memory(session_id, "result_key", {"output": "some work"})

    result = runner.execute_skill(
        tool_name="review_work",
        arguments={
            "objective": "Verify result exists",
            "memory_key": "result_key",
        },
        session_id=session_id,
    )
    assert result.status == "success"
    review = json.loads(result.content)
    assert review["verdict"] == "pass"
    assert "A result exists" in review["summary"]


def test_review_work_writes_to_output_key(tmp_path: Path) -> None:
    runner, session_id, database = _runner(tmp_path)
    database.write_memory(session_id, "result_key", {"output": "work"})

    result = runner.execute_skill(
        tool_name="review_work",
        arguments={
            "objective": "Check custom output",
            "memory_key": "result_key",
            "output_key": "my_review_output",
        },
        session_id=session_id,
    )
    assert result.status == "success"

    memory = database.read_memory(session_id, "my_review_output")
    assert isinstance(memory, dict)
    assert memory["verdict"] == "pass"


def test_review_work_uses_default_output_key(tmp_path: Path) -> None:
    runner, session_id, database = _runner(tmp_path)
    database.write_memory(session_id, "result_key", {"output": "work"})

    runner.execute_skill(
        tool_name="review_work",
        arguments={
            "objective": "Check default output key",
            "memory_key": "result_key",
        },
        session_id=session_id,
    )

    memory = database.read_memory(session_id, "result_key_review")
    assert isinstance(memory, dict)
    assert memory["verdict"] == "pass"


def _runner(tmp_path: Path) -> tuple[SkillRunner, str, BlackboardDatabase]:
    config = _test_config(tmp_path)
    database = BlackboardDatabase(config.runtime.database_path)
    database.create_tables()
    session_id = database.start_session("test")
    return SkillRunner(database=database, config=config), session_id, database


def _test_config(tmp_path: Path) -> HarnessConfig:
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
            database_path=tmp_path / "blackboard.db",
            default_container_image="python:3.12-slim",
        ),
        observability=ObservabilityConfig(logfire_enabled=False),
        llm=LLMConfig(provider="deepseek", model="deepseek-v4-flash", base_url=None),
    )
