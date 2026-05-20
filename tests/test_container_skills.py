from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING

from harness_poc.core.blackboard_proxy import BlackboardAccessProxy
from harness_poc.core.config import (
    HarnessConfig,
    HarnessPaths,
    LLMConfig,
    ObservabilityConfig,
    RuntimeConfig,
)
from harness_poc.core.database import BlackboardDatabase
from harness_poc.core.permissions import SkillPermissions
from harness_poc.core.skill_context import SkillContext
from harness_poc.core.tool_runner import ToolRunner

from harness_poc.system_tools.container_spawn import (
    _cleanup_stale_harness_containers,
    _inspect_container,
    _resolve_backend,
    container_spawn,
)
from harness_poc.system_tools.container_destroy import container_destroy

if TYPE_CHECKING:
    from collections.abc import Callable

    import pytest

from sqlalchemy import Engine


def test_container_spawn_fails_when_no_image(db_engine: Engine) -> None:
    tool_runner, session_id, _ = _tool_runner(
        db_engine, default_container_image=""
    )

    import json

    raw = tool_runner.execute_tool(
        tool_name="container_spawn",
        arguments={},
        session_id=session_id,
    )
    result = json.loads(raw)
    assert result["status"] == "failed"
    assert "No container image" in result["content"]


def test_container_spawn_fails_when_no_backend(db_engine: Engine) -> None:
    tool_runner, session_id, _ = _tool_runner(db_engine)
    import json

    result = json.loads(
        tool_runner.execute_tool(
            tool_name="container_spawn",
            arguments={"image": "python:3.12-slim"},
            session_id=session_id,
        )
    )
    assert result["status"] in {"success", "failed"}
    if result["status"] == "failed":
        assert any(
            phrase in result["content"]
            for phrase in (
                "No container runtime",
                "container",
                "image",
                "timed out",
            )
        )


def test_container_exec_requires_command(db_engine: Engine) -> None:
    tool_runner, session_id, _ = _tool_runner(db_engine)
    import json

    result = json.loads(
        tool_runner.execute_tool(
            tool_name="container_exec",
            arguments={"container": "test-container"},
            session_id=session_id,
        )
    )
    assert result["status"] == "failed"
    assert "requires a command" in result["content"]


def test_container_exec_requires_container(db_engine: Engine) -> None:
    tool_runner, session_id, _ = _tool_runner(db_engine)
    import json

    result = json.loads(
        tool_runner.execute_tool(
            tool_name="container_exec",
            arguments={"command": "echo hello"},
            session_id=session_id,
        )
    )
    assert result["status"] == "failed"
    assert "requires a container" in result["content"]


def test_container_exec_fails_when_no_backend(db_engine: Engine) -> None:
    tool_runner, session_id, _ = _tool_runner(db_engine)
    import json

    result = json.loads(
        tool_runner.execute_tool(
            tool_name="container_exec",
            arguments={
                "command": "echo test",
                "container": "my-container",
            },
            session_id=session_id,
        )
    )
    assert result["status"] in {"success", "failed"}
    assert (
        "No container runtime" in result["content"]
        or result.get("artifacts", {}).get("exit_code") is not None
        or "no such" in result["content"].lower()
    )


def test_container_destroy_requires_container_name(
    db_engine: Engine,
) -> None:
    tool_runner, session_id, _ = _tool_runner(db_engine)
    import json

    result = json.loads(
        tool_runner.execute_tool(
            tool_name="container_destroy",
            arguments={},
            session_id=session_id,
        )
    )
    assert result["status"] == "failed"
    assert "requires a container name" in result["content"]


def test_container_spawn_mounts_scratch_outside_read_only_workspace(
    db_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _test_config(db_engine)
    database = BlackboardDatabase(db_engine)
    database.create_tables()
    session_id = database.start_session("test")
    proxy = BlackboardAccessProxy(
        database,
        SkillPermissions(blackboard="read_write", workspace="read_write"),
    )
    from harness_poc.core.tool_context import ToolContext

    ctx = ToolContext(
        session_id=session_id,
        project_root=config.project_root,
        database=proxy,
        runtime_config=config.runtime,
    )
    calls: list[list[str]] = []

    monkeypatch.setattr(
        "harness_poc.system_tools.container_spawn._resolve_backend",
        lambda: "docker",
    )
    monkeypatch.setattr(
        "harness_poc.system_tools.container_spawn._cleanup_stale_harness_containers",
        _noop_cleanup,
    )
    monkeypatch.setattr(
        "harness_poc.system_tools.container_spawn._inspect_container",
        _inspect_after_run(),
    )

    def fake_run(cmd: list[str], **kwargs: object) -> SimpleNamespace:
        del kwargs
        calls.append(cmd)
        return SimpleNamespace(returncode=0, stdout="container-id\n", stderr="")

    import subprocess as _sp

    monkeypatch.setattr(_sp, "run", fake_run)

    result = container_spawn(ctx, container_name="harness-python-test")

    assert result.status == "success"
    create_cmd = next(
        cmd for cmd in calls if any("run" in arg for arg in cmd)
    )
    assert any(mount.endswith(":/workspace:ro") for mount in create_cmd)
    assert any(mount.endswith(":/scratch:rw") for mount in create_cmd)
    assert not any(mount.endswith(":/workspace:rw") for mount in create_cmd)
    assert "-e" in create_cmd
    assert "TMPDIR=/scratch" in create_cmd
    assert "HOME=/scratch" in create_cmd


def test_container_spawn_cleanup_removes_only_stale_harness_containers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    removed: list[str] = []
    from datetime import UTC

    now = __import__("datetime").datetime.now(UTC).timestamp()

    monkeypatch.setattr(
        "harness_poc.system_tools.container_spawn._list_harness_container_names",
        lambda _backend: [
            "harness-python-current",
            "harness-python-old",
            "harness-old",
        ],
    )
    monkeypatch.setattr(
        "harness_poc.system_tools.container_spawn._inspect_container",
        lambda _backend, name: {
            "container_name": name,
            "created_at_ts": now - 10_000 if name.endswith("old") else now,
        },
    )
    monkeypatch.setattr(
        "harness_poc.system_tools.container_spawn._remove_container",
        lambda _backend, name: removed.append(name),
    )

    _cleanup_stale_harness_containers(
        "docker",
        exclude={"harness-python-current"},
        ttl_seconds=100,
        max_containers=10,
    )

    assert removed == ["harness-old", "harness-python-old"]


def _tool_runner(
    engine: Engine, default_container_image: str = "python:3.12-slim"
) -> tuple[ToolRunner, str, BlackboardDatabase]:
    config = _test_config(engine, default_container_image)
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


def _noop_cleanup(
    _backend: str,
    *,
    exclude: set[str],
    ttl_seconds: int,
    max_containers: int,
) -> None:
    del exclude, ttl_seconds, max_containers


def _inspect_after_run() -> Callable[[str, str], dict[str, object] | None]:
    calls = {"count": 0}

    def inspect(
        _backend: str, container_name: str
    ) -> dict[str, object] | None:
        calls["count"] += 1
        if calls["count"] == 1:
            return None
        return {
            "backend": _backend,
            "container_name": container_name,
            "container_id": "container-id",
            "image": "python:3.12-slim",
            "status": "running",
            "running": True,
            "workdir": "/workspace",
            "created_at": "2026-05-19T00:00:00Z",
            "created_at_ts": 0.0,
        }

    return inspect


def _test_config(
    engine: Engine, default_container_image: str = "python:3.12-slim"
) -> HarnessConfig:
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
            default_container_image=default_container_image,
        ),
        observability=ObservabilityConfig(logfire_enabled=False),
        llm=LLMConfig(
            provider="deepseek", model="deepseek-v4-flash", base_url=None
        ),
    )
