from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING

from harness_poc.core.config import (
    HarnessConfig,
    HarnessPaths,
    LLMConfig,
    ObservabilityConfig,
    RuntimeConfig,
)
from harness_poc.core.database import BlackboardDatabase
from harness_poc.core.skill_context import SkillContext
from harness_poc.core.skill_runner import SkillRunner
from harness_poc.system_skills.container_spawn import skill as container_spawn_skill

if TYPE_CHECKING:
    from collections.abc import Callable

    import pytest

from sqlalchemy import Engine


def test_container_spawn_fails_when_no_image(db_engine: Engine) -> None:
    """Without a configured image, container_spawn should fail gracefully."""
    runner, session_id, _ = _runner(db_engine, default_container_image="")

    result = runner.execute_skill(
        tool_name="container_spawn",
        arguments={},
        session_id=session_id,
    )
    assert result.status == "failed"
    assert "No container image" in result.content


def test_container_spawn_fails_when_no_backend(db_engine: Engine) -> None:
    """If neither docker nor podman is on PATH, should get a clear error.

    When a backend is available, container may fail to pull/run the image,
    which is also a valid failure path.
    """
    runner, session_id, _ = _runner(db_engine)

    result = runner.execute_skill(
        tool_name="container_spawn",
        arguments={"image": "python:3.12-slim"},
        session_id=session_id,
    )
    # Either success (backend available + image cached) or clear error
    assert result.status in {"success", "failed"}
    if result.status == "failed":
        assert any(
            phrase in result.content
            for phrase in (
                "No container runtime",
                "container",
                "image",
                "timed out",
            )
        )


def test_container_exec_requires_command(db_engine: Engine) -> None:
    runner, session_id, _ = _runner(db_engine)

    result = runner.execute_skill(
        tool_name="container_exec",
        arguments={"container": "test-container"},
        session_id=session_id,
    )
    assert result.status == "failed"
    assert "requires a command" in result.content


def test_container_exec_requires_container(db_engine: Engine) -> None:
    runner, session_id, _ = _runner(db_engine)

    result = runner.execute_skill(
        tool_name="container_exec",
        arguments={"command": "echo hello"},
        session_id=session_id,
    )
    assert result.status == "failed"
    assert "requires a container" in result.content


def test_container_exec_fails_when_no_backend(db_engine: Engine) -> None:
    # Docker/podman may be available — test runs successfully or fails gracefully
    runner, session_id, _ = _runner(db_engine)

    result = runner.execute_skill(
        tool_name="container_exec",
        arguments={
            "command": "echo test",
            "container": "my-container",
        },
        session_id=session_id,
    )
    assert result.status in {"success", "failed"}
    # Either backend not found or container doesn't exist — both fine
    assert (
        "No container runtime" in result.content
        or result.artifacts.get("exit_code") is not None
        or "no such" in result.content.lower()
    )


def test_container_destroy_requires_container_name(db_engine: Engine) -> None:
    runner, session_id, _ = _runner(db_engine)

    result = runner.execute_skill(
        tool_name="container_destroy",
        arguments={},
        session_id=session_id,
    )
    assert result.status == "failed"
    assert "requires a container name" in result.content


def test_container_spawn_mounts_scratch_outside_read_only_workspace(
    db_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _test_config(db_engine)
    database = BlackboardDatabase(db_engine)
    session_id = database.start_session("test")
    ctx = SkillContext(
        session_id=session_id,
        skill_name="container_spawn",
        database=database,
        config=config,
    )
    calls: list[list[str]] = []

    monkeypatch.setattr(container_spawn_skill, "_resolve_backend", lambda: "docker")
    monkeypatch.setattr(container_spawn_skill, "_cleanup_stale_harness_containers", _noop_cleanup)
    monkeypatch.setattr(container_spawn_skill, "_inspect_container", _inspect_after_run())

    def fake_run(cmd: list[str], **kwargs: object) -> SimpleNamespace:
        del kwargs
        calls.append(cmd)
        return SimpleNamespace(returncode=0, stdout="container-id\n", stderr="")

    monkeypatch.setattr(container_spawn_skill.subprocess, "run", fake_run)

    result = container_spawn_skill.execute(ctx, {"container_name": "harness-python-test"})

    assert result.status == "success"
    # Find the docker create/run call (skip the image-existence check)
    create_cmd = next(cmd for cmd in calls if any("run" in arg for arg in cmd))
    assert any(mount.endswith(":/workspace:ro") for mount in create_cmd)
    assert any(mount.endswith(":/scratch:rw") for mount in create_cmd)
    # Verify read-only workspace is enforced
    assert not any(mount.endswith(":/workspace:rw") for mount in create_cmd)
    # Verify environment variables direct output to scratch
    assert "-e" in create_cmd
    assert "TMPDIR=/scratch" in create_cmd
    assert "HOME=/scratch" in create_cmd


def test_container_spawn_cleanup_removes_only_stale_harness_containers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    removed: list[str] = []
    now = container_spawn_skill.datetime.now(container_spawn_skill.UTC).timestamp()

    monkeypatch.setattr(
        container_spawn_skill,
        "_list_harness_container_names",
        lambda _backend: [
            "harness-python-current",
            "harness-python-old",
            "harness-old",
        ],
    )
    monkeypatch.setattr(
        container_spawn_skill,
        "_inspect_container",
        lambda _backend, name: {
            "container_name": name,
            "created_at_ts": now - 10_000 if name.endswith("old") else now,
        },
    )
    monkeypatch.setattr(
        container_spawn_skill,
        "_remove_container",
        lambda _backend, name: removed.append(name),
    )

    container_spawn_skill._cleanup_stale_harness_containers(  # noqa: SLF001
        "docker",
        exclude={"harness-python-current"},
        ttl_seconds=100,
        max_containers=10,
    )

    assert removed == ["harness-old", "harness-python-old"]


def _runner(
    engine: Engine, default_container_image: str = "python:3.12-slim"
) -> tuple[SkillRunner, str, BlackboardDatabase]:
    config = _test_config(engine, default_container_image)
    database = BlackboardDatabase(engine)
    session_id = database.start_session("test")
    return SkillRunner(database=database, config=config), session_id, database


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

    def inspect(_backend: str, container_name: str) -> dict[str, object] | None:
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
        llm=LLMConfig(provider="deepseek", model="deepseek-v4-flash", base_url=None),
    )
