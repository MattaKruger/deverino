from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from harness_poc.repl import handle_repl_input

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

    from harness_poc.app_factory import AppState


def test_direct_skill_invocation_dispatches_without_chat(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app_state = _fake_app_state(tmp_path)
    calls: dict[str, Any] = {}

    monkeypatch.setattr(
        "harness_poc.repl.execute_named_tool",
        lambda _app_state, skill_name, argument: calls.update(
            {"skill": skill_name, "argument": argument}
        ),
    )
    monkeypatch.setattr(
        "harness_poc.repl.handle_chat_input",
        lambda _app_state, user_input: calls.update({"chat": user_input}),
    )

    handle_repl_input(app_state, "/execute_python code='print(1)'")

    assert calls == {"skill": "execute_python", "argument": "code='print(1)'"}


def test_direct_workflow_invocation_dispatches_without_tui_cli(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflows_dir = tmp_path / "workflows"
    workflows_dir.mkdir()
    (workflows_dir / "research_task.yaml").write_text("states: {}\n", encoding="utf-8")
    app_state = _fake_app_state(tmp_path, workflows_dir=workflows_dir)
    calls: dict[str, Any] = {}

    monkeypatch.setattr(
        "harness_poc.repl.run_workflow",
        lambda _app_state, workflow_name, objective: (
            calls.update({"workflow": workflow_name, "objective": objective}) or True
        ),
    )
    monkeypatch.setattr(
        "harness_poc.repl.handle_chat_input",
        lambda _app_state, user_input: calls.update({"chat": user_input}),
    )

    handle_repl_input(app_state, "/research_task gather context")

    assert calls == {"workflow": "research_task", "objective": "gather context"}


def test_direct_pipeline_invocation_dispatches_without_chat(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app_state = _fake_app_state(tmp_path, pipelines=("research_and_write",))
    calls: dict[str, Any] = {}

    monkeypatch.setattr(
        "harness_poc.repl.run_pipeline",
        lambda _app_state, pipeline_name, inputs: (
            calls.update({"pipeline": pipeline_name, "inputs": inputs}) or True
        ),
    )
    monkeypatch.setattr(
        "harness_poc.repl.handle_chat_input",
        lambda _app_state, user_input: calls.update({"chat": user_input}),
    )

    handle_repl_input(app_state, "/research_and_write topic=autocomplete depth=shallow")

    assert calls == {
        "pipeline": "research_and_write",
        "inputs": {"topic": "autocomplete", "depth": "shallow"},
    }


def test_plain_skill_name_remains_chat_input(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app_state = _fake_app_state(tmp_path)
    calls: dict[str, Any] = {}

    monkeypatch.setattr(
        "harness_poc.repl.handle_chat_input",
        lambda _app_state, user_input: calls.update({"chat": user_input}),
    )

    handle_repl_input(app_state, "execute_python should not hijack prose")

    assert calls == {"chat": "execute_python should not hijack prose"}


def _fake_app_state(
    tmp_path: Path,
    *,
    workflows_dir: Path | None = None,
    pipelines: tuple[str, ...] = (),
) -> AppState:
    if workflows_dir is None:
        workflows_dir = tmp_path / "workflows"
        workflows_dir.mkdir()
    return cast(
        "AppState",
        _FakeAppState(
            config=_FakeConfig(paths=_FakePaths(workflows=workflows_dir)),
            skill_runner=_FakeSkillRunner(),
            pipeline_runner=_FakePipelineRunner(pipelines),
        ),
    )


@dataclass(frozen=True, slots=True)
class _FakePaths:
    workflows: Path


@dataclass(frozen=True, slots=True)
class _FakeConfig:
    paths: _FakePaths


class _FakeSkillRunner:
    @staticmethod
    def discover_skills() -> list[dict[str, Any]]:
        return [{"function": {"name": "execute_python"}}]


class _FakePipelineRunner:
    def __init__(self, pipelines: tuple[str, ...]) -> None:
        self._pipelines = pipelines

    def list_pipelines(self) -> list[str]:
        return list(self._pipelines)


@dataclass(slots=True)
class _FakeAppState:
    config: _FakeConfig
    skill_runner: _FakeSkillRunner
    pipeline_runner: _FakePipelineRunner
