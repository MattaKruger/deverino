from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pytest

from sqlalchemy import Engine

from harness_poc.core.config import (
    HarnessConfig,
    HarnessPaths,
    LLMConfig,
    ObservabilityConfig,
    RuntimeConfig,
)
from harness_poc.core.permissions import SkillPermissions
from harness_poc.core.skills import SkillResult
from harness_poc.core.storage import BlackboardAccessProxy, BlackboardDatabase
from harness_poc.core.tools import ToolContext, ToolRunner

CUSTOM_TIMEOUT_SECONDS = 7


def test_execute_python_is_a_builtin_tool(db_engine: Engine) -> None:
    """execute_python is now a built-in tool, not a skill-backed one."""
    tool_runner, _session_id, _database = _tool_runner(db_engine)
    tool_names = tool_runner.list_tool_names()
    assert "execute_python" in tool_names


def test_execute_python_requires_code(db_engine: Engine) -> None:
    tool_runner, session_id, _database = _tool_runner(db_engine)

    raw = tool_runner.execute_tool(
        tool_name="execute_python",
        arguments={},
        session_id=session_id,
    )
    data = json.loads(raw)
    assert data["status"] == "failed"
    assert "requires Python code" in data["content"]


def test_execute_python_spawns_container_and_executes_encoded_code(
    db_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool_runner, session_id, _database = _tool_runner(db_engine)
    calls: dict[str, Any] = {}

    def fake_spawn(ctx: ToolContext, image: str = "", container_name: str = "") -> SkillResult:
        calls["spawn"] = {
            "session_id": ctx.session_id,
            "container_name": container_name,
            "image": image,
        }
        return SkillResult(
            status="success",
            content="spawned",
            artifacts={
                "backend": "docker",
                "container_name": "test-python-container",
            },
        )

    def fake_exec(
        command: str = "",
        container: str = "",
        backend: str = "auto",
        workdir: str = "",
        timeout_seconds: int | None = None,
        cancellation: object | None = None,
    ) -> SkillResult:
        del backend, workdir, cancellation
        calls["exec"] = {
            "command": command,
            "container": container,
            "timeout_seconds": timeout_seconds,
        }
        return SkillResult(
            status="success",
            content="exec",
            artifacts={
                "backend": "docker",
                "container": container,
                "exit_code": 0,
                "stdout": "3",
                "stderr": "",
            },
        )

    import harness_poc.system_tools.execute_python as ep_module

    monkeypatch.setattr(ep_module, "container_spawn", fake_spawn)
    monkeypatch.setattr(ep_module, "container_exec", fake_exec)

    raw = tool_runner.execute_tool(
        tool_name="execute_python",
        arguments={
            "code": "print(1 + 2)",
            "timeout_seconds": CUSTOM_TIMEOUT_SECONDS,
        },
        session_id=session_id,
    )
    data = json.loads(raw)

    assert data["status"] == "success"
    assert data["artifacts"]["container"] == "test-python-container"
    assert data["artifacts"]["stdout"] == "3"
    assert data["artifacts"]["timeout_seconds"] == CUSTOM_TIMEOUT_SECONDS
    assert data["artifacts"]["spawned_container"] is True
    assert calls["spawn"]["container_name"].startswith("harness-python-")
    assert calls["exec"]["container"] == "test-python-container"
    assert calls["exec"]["timeout_seconds"] == CUSTOM_TIMEOUT_SECONDS
    assert "print(1 + 2)" not in calls["exec"]["command"]
    assert "base64.b64decode" in calls["exec"]["command"]


def test_execute_python_uses_existing_container_without_spawning(
    db_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool_runner, session_id, _database = _tool_runner(db_engine)
    spawned = False

    def fake_spawn(ctx: ToolContext, image: str = "", container_name: str = "") -> SkillResult:
        del ctx, image, container_name
        nonlocal spawned
        spawned = True
        return SkillResult(status="success", content="spawned")

    def fake_exec(
        command: str = "",
        container: str = "",
        backend: str = "auto",
        workdir: str = "",
        timeout_seconds: int | None = None,
        cancellation: object | None = None,
    ) -> SkillResult:
        del command, backend, workdir, timeout_seconds, cancellation
        return SkillResult(
            status="success",
            content="exec",
            artifacts={
                "backend": "docker",
                "container": container,
                "exit_code": 0,
                "stdout": "ok",
                "stderr": "",
            },
        )

    import harness_poc.system_tools.execute_python as ep_module

    monkeypatch.setattr(ep_module, "container_spawn", fake_spawn)
    monkeypatch.setattr(ep_module, "container_exec", fake_exec)

    raw = tool_runner.execute_tool(
        tool_name="execute_python",
        arguments={
            "code": "print('ok')",
            "container": "existing-container",
        },
        session_id=session_id,
    )
    data = json.loads(raw)

    assert spawned is False
    assert data["status"] == "success"
    assert data["artifacts"]["container"] == "existing-container"
    assert data["artifacts"]["spawned_container"] is False


def test_execute_python_caps_model_visible_stdout(
    db_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool_runner, session_id, _database = _tool_runner(db_engine)

    from harness_poc.system_tools.execute_python import MAX_STDOUT_CHARS

    large_stdout = "x" * (MAX_STDOUT_CHARS + 100)

    def fake_exec(
        command: str = "",
        container: str = "",
        backend: str = "auto",
        workdir: str = "",
        timeout_seconds: int | None = None,
        cancellation: object | None = None,
    ) -> SkillResult:
        del command, backend, workdir, timeout_seconds, cancellation
        return SkillResult(
            status="success",
            content="exec",
            artifacts={
                "backend": "docker",
                "container": container,
                "exit_code": 0,
                "stdout": large_stdout,
                "stderr": "",
            },
        )

    import harness_poc.system_tools.execute_python as ep_module

    monkeypatch.setattr(ep_module, "container_exec", fake_exec)

    raw = tool_runner.execute_tool(
        tool_name="execute_python",
        arguments={
            "code": "print('many')",
            "container": "existing-container",
        },
        session_id=session_id,
    )
    data = json.loads(raw)

    # The content is JSON, so the total string includes JSON overhead.
    # Check the artifacts instead for truncation stats.
    assert "execute_python output truncated" in data["content"]
    assert data["artifacts"]["stdout_truncated"] is True
    assert data["artifacts"]["stdout_original_chars"] == len(large_stdout)


def _tool_runner(
    engine: Engine,
) -> tuple[ToolRunner, str, BlackboardDatabase]:
    config = _test_config(engine)
    database = BlackboardDatabase(engine)
    database.create_tables()
    session_id = database.start_session("test")
    proxy = BlackboardAccessProxy(
        database,
        SkillPermissions(blackboard="read_write", workspace="read_write"),
    )
    runner = ToolRunner(
        config=config,
        database=proxy,
        runtime_config=config.runtime,
    )
    return runner, session_id, database


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
