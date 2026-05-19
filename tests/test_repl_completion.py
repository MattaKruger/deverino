from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from prompt_toolkit.document import Document

from harness_poc.repl_completion import HarnessCompleter, HarnessSuggester

if TYPE_CHECKING:
    from harness_poc.app_factory import AppState


def test_slash_root_completion_includes_discovery_commands() -> None:
    completions = _completion_texts("/")

    assert "/skills" in completions
    assert "/workflows" in completions
    assert "/workflow" in completions
    assert "/pipelines" in completions
    assert "/pipeline" in completions


def test_workflow_completion_uses_workflow_files() -> None:
    completions = _completion_texts("/workflow r")

    assert "research_task" in completions
    assert "research_plan_execute" in completions


def test_skill_show_completion_uses_discovered_skills() -> None:
    completions = _completion_texts("/skill show con")

    assert "consolidate_state" in completions


def test_skill_command_completion_includes_executable_skill_names() -> None:
    completions = _completion_texts("/skill con")

    assert "consolidate_state" in completions


def test_root_completion_includes_direct_resource_invocations() -> None:
    completions = _completion_texts("/con")

    assert "/consolidate_state" in completions


async def test_tui_suggester_uses_repl_completions() -> None:
    suggestion = await HarnessSuggester(cast("AppState", _FakeAppState())).get_suggestion("/con")

    assert suggestion == "/consolidate_state"


def _completion_texts(text: str) -> set[str]:
    completer = HarnessCompleter(cast("AppState", _FakeAppState()))
    return {completion.text for completion in completer.get_completions(Document(text), object())}


@dataclass(frozen=True, slots=True)
class _FakeConfig:
    paths: Any


@dataclass(frozen=True, slots=True)
class _FakePaths:
    workflows: Path


class _FakeSkillRunner:
    @staticmethod
    def discover_skills() -> list[dict[str, Any]]:
        return [
            {"function": {"name": "consolidate_state"}},
            {"function": {"name": "container_exec"}},
        ]


class _FakePipelineRunner:
    @staticmethod
    def list_pipelines() -> list[str]:
        return ["research_and_write"]


class _FakeAppState:
    config = _FakeConfig(paths=_FakePaths(workflows=Path.cwd() / "workflows"))
    skill_runner = _FakeSkillRunner()
    pipeline_runner = _FakePipelineRunner()
