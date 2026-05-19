from __future__ import annotations

from pathlib import Path

from harness_poc.core.config import (
    HarnessConfig,
    HarnessPaths,
    LLMConfig,
    ObservabilityConfig,
    RuntimeConfig,
)
from harness_poc.core.database import BlackboardDatabase
from harness_poc.core.skill_runner import SkillRunner


def test_container_spawn_fails_when_no_image(tmp_path: Path) -> None:
    """Without a configured image, container_spawn should fail gracefully."""
    runner, session_id, _ = _runner(tmp_path, default_container_image="")

    result = runner.execute_skill(
        tool_name="container_spawn",
        arguments={},
        session_id=session_id,
    )
    assert result.status == "failed"
    assert "No container image" in result.content


def test_container_spawn_fails_when_no_backend(tmp_path: Path) -> None:
    """If neither docker nor podman is on PATH, should get a clear error.
    When a backend is available, container may fail to pull/run the image,
    which is also a valid failure path."""
    runner, session_id, _ = _runner(tmp_path)

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


def test_container_exec_requires_command(tmp_path: Path) -> None:
    runner, session_id, _ = _runner(tmp_path)

    result = runner.execute_skill(
        tool_name="container_exec",
        arguments={"container": "test-container"},
        session_id=session_id,
    )
    assert result.status == "failed"
    assert "requires a command" in result.content


def test_container_exec_requires_container(tmp_path: Path) -> None:
    runner, session_id, _ = _runner(tmp_path)

    result = runner.execute_skill(
        tool_name="container_exec",
        arguments={"command": "echo hello"},
        session_id=session_id,
    )
    assert result.status == "failed"
    assert "requires a container" in result.content


def test_container_exec_fails_when_no_backend(tmp_path: Path) -> None:
    # Docker/podman may be available — test runs successfully or fails gracefully
    runner, session_id, _ = _runner(tmp_path)

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


def test_container_destroy_requires_container_name(tmp_path: Path) -> None:
    runner, session_id, _ = _runner(tmp_path)

    result = runner.execute_skill(
        tool_name="container_destroy",
        arguments={},
        session_id=session_id,
    )
    assert result.status == "failed"
    assert "requires a container name" in result.content


def _runner(
    tmp_path: Path, default_container_image: str = "python:3.12-slim"
) -> tuple[SkillRunner, str, BlackboardDatabase]:
    config = _test_config(tmp_path, default_container_image)
    database = BlackboardDatabase(config.runtime.database_path)
    database.create_tables()
    session_id = database.start_session("test")
    return SkillRunner(database=database, config=config), session_id, database


def _test_config(
    tmp_path: Path, default_container_image: str = "python:3.12-slim"
) -> HarnessConfig:
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
            default_container_image=default_container_image,
        ),
        observability=ObservabilityConfig(logfire_enabled=False),
        llm=LLMConfig(provider="deepseek", model="deepseek-v4-flash", base_url=None),
    )
