from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pytest

from harness_poc.core.config import (
    HarnessConfig,
    HarnessPaths,
    LLMConfig,
    ObservabilityConfig,
    RuntimeConfig,
)
from harness_poc.core.database import BlackboardDatabase
from harness_poc.core.pydantic_runtime import build_skill_tools
from harness_poc.core.skill_context import SkillContext, SkillResult
from harness_poc.core.skill_runner import SkillRunner
from harness_poc.system_skills.container_exec import (
    skill as container_exec_skill,
)
from harness_poc.system_skills.container_spawn import (
    skill as container_spawn_skill,
)
from harness_poc.system_skills.execute_python import (
    skill as execute_python_skill,
)

CUSTOM_TIMEOUT_SECONDS = 7


def test_execute_python_is_auto_invokable(tmp_path: Path) -> None:
    runner, _session_id, _database = _runner(tmp_path)

    tools = build_skill_tools(runner)
    tool_by_name = {tool.name: tool for tool in tools}

    assert "execute_python" in tool_by_name
    assert "code" in tool_by_name["execute_python"].function_schema.json_schema["properties"]


def test_execute_python_requires_code(tmp_path: Path) -> None:
    runner, session_id, _database = _runner(tmp_path)

    result = runner.execute_skill(
        tool_name="execute_python",
        arguments={},
        session_id=session_id,
    )

    assert result.status == "failed"
    assert "requires Python code" in result.content
    assert result.artifacts["error"] == "missing_code"


def test_execute_python_spawns_container_and_executes_encoded_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, session_id, _database = _runner(tmp_path)
    calls: dict[str, Any] = {}

    def fake_spawn(ctx: SkillContext, arguments: dict[str, Any]) -> SkillResult:
        calls["spawn"] = {"session_id": ctx.session_id, "arguments": arguments}
        return SkillResult(
            status="success",
            content="spawned",
            artifacts={
                "backend": "docker",
                "container_name": "test-python-container",
            },
        )

    def fake_exec(ctx: SkillContext, arguments: dict[str, Any]) -> SkillResult:
        calls["exec"] = {"session_id": ctx.session_id, "arguments": arguments}
        return SkillResult(
            status="success",
            content="exec",
            artifacts={
                "backend": "docker",
                "container": arguments["container"],
                "exit_code": 0,
                "stdout": "3",
                "stderr": "",
            },
        )

    monkeypatch.setattr(container_spawn_skill, "execute", fake_spawn)
    monkeypatch.setattr(container_exec_skill, "execute", fake_exec)

    result = runner.execute_skill(
        tool_name="execute_python",
        arguments={
            "code": "print(1 + 2)",
            "timeout_seconds": CUSTOM_TIMEOUT_SECONDS,
        },
        session_id=session_id,
    )

    assert result.status == "success"
    assert result.artifacts["container"] == "test-python-container"
    assert result.artifacts["stdout"] == "3"
    assert result.artifacts["timeout_seconds"] == CUSTOM_TIMEOUT_SECONDS
    assert result.artifacts["spawned_container"] is True
    assert calls["spawn"]["arguments"]["container_name"].startswith("harness-python-")
    assert calls["exec"]["arguments"]["container"] == "test-python-container"
    assert calls["exec"]["arguments"]["timeout_seconds"] == CUSTOM_TIMEOUT_SECONDS
    assert "print(1 + 2)" not in calls["exec"]["arguments"]["command"]
    assert "base64.b64decode" in calls["exec"]["arguments"]["command"]


def test_execute_python_uses_existing_container_without_spawning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, session_id, _database = _runner(tmp_path)
    spawned = False

    def fake_spawn(ctx: SkillContext, arguments: dict[str, Any]) -> SkillResult:
        del ctx, arguments
        nonlocal spawned
        spawned = True
        return SkillResult(status="success", content="spawned")

    def fake_exec(ctx: SkillContext, arguments: dict[str, Any]) -> SkillResult:
        del ctx
        return SkillResult(
            status="success",
            content="exec",
            artifacts={
                "backend": "docker",
                "container": arguments["container"],
                "exit_code": 0,
                "stdout": "ok",
                "stderr": "",
            },
        )

    monkeypatch.setattr(container_spawn_skill, "execute", fake_spawn)
    monkeypatch.setattr(container_exec_skill, "execute", fake_exec)

    result = runner.execute_skill(
        tool_name="execute_python",
        arguments={"code": "print('ok')", "container": "existing-container"},
        session_id=session_id,
    )

    assert spawned is False
    assert result.status == "success"
    assert result.artifacts["container"] == "existing-container"
    assert result.artifacts["spawned_container"] is False


def test_execute_python_caps_model_visible_stdout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, session_id, _database = _runner(tmp_path)
    large_stdout = "x" * (execute_python_skill.MAX_STDOUT_CHARS + 100)

    def fake_exec(ctx: SkillContext, arguments: dict[str, Any]) -> SkillResult:
        del ctx
        return SkillResult(
            status="success",
            content="exec",
            artifacts={
                "backend": "docker",
                "container": arguments["container"],
                "exit_code": 0,
                "stdout": large_stdout,
                "stderr": "",
            },
        )

    monkeypatch.setattr(container_exec_skill, "execute", fake_exec)

    result = runner.execute_skill(
        tool_name="execute_python",
        arguments={"code": "print('many')", "container": "existing-container"},
        session_id=session_id,
    )

    content = json.loads(result.content)
    assert len(content["stdout"]) < len(large_stdout)
    assert "execute_python output truncated" in result.content
    assert result.artifacts["stdout_truncated"] is True
    assert result.artifacts["stdout_original_chars"] == len(large_stdout)


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
