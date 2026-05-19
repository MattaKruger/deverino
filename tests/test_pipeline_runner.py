from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from harness_poc.core.events import (
    PipelineCompleted,
    PipelineNodeCompleted,
    PipelineNodeStarted,
    PipelineStarted,
)
from harness_poc.core.pipeline_runner import PipelineRunner, build_waves
from harness_poc.core.skill_context import SkillResult
from tests.helpers import RecordingEventBus

if TYPE_CHECKING:
    from pathlib import Path


# --- build_waves ---


def test_build_waves_no_deps() -> None:
    nodes = [
        {"id": "a", "type": "skill"},
        {"id": "b", "type": "skill"},
    ]
    waves = build_waves(nodes)
    assert len(waves) == 1
    assert {n["id"] for n in waves[0]} == {"a", "b"}


def test_build_waves_sequential() -> None:
    nodes = [
        {"id": "a", "type": "skill"},
        {"id": "b", "type": "skill", "depends_on": ["a"]},
        {"id": "c", "type": "skill", "depends_on": ["b"]},
    ]
    waves = build_waves(nodes)
    assert len(waves) == 3  # noqa: PLR2004
    assert waves[0][0]["id"] == "a"
    assert waves[1][0]["id"] == "b"
    assert waves[2][0]["id"] == "c"


def test_build_waves_mixed() -> None:
    nodes = [
        {"id": "web", "type": "agent"},
        {"id": "mem", "type": "skill"},
        {"id": "synth", "type": "agent", "depends_on": ["web", "mem"]},
    ]
    waves = build_waves(nodes)
    assert len(waves) == 2  # noqa: PLR2004
    assert {n["id"] for n in waves[0]} == {"web", "mem"}
    assert waves[1][0]["id"] == "synth"


def test_build_waves_unknown_dep_raises() -> None:
    nodes = [{"id": "a", "type": "skill", "depends_on": ["ghost"]}]
    with pytest.raises(ValueError, match="unknown node"):
        build_waves(nodes)


def test_build_waves_circular_dep_raises() -> None:
    nodes = [
        {"id": "a", "type": "skill", "depends_on": ["b"]},
        {"id": "b", "type": "skill", "depends_on": ["a"]},
    ]
    with pytest.raises(ValueError, match="Circular dependency"):
        build_waves(nodes)


# --- PipelineRunner helpers ---


def _write_pipeline(tmp_path: Path, content: str) -> Path:
    pipelines_dir = tmp_path / "pipelines"
    pipelines_dir.mkdir()
    (pipelines_dir / "test_pipe.yaml").write_text(textwrap.dedent(content))
    return pipelines_dir


def _make_app_state() -> MagicMock:
    skill_runner = MagicMock()
    skill_runner.execute_skill.return_value = SkillResult(
        status="success", content="skill-output", artifacts={}
    )
    state = MagicMock()
    state.session_id = "sess-1"
    state.event_bus = RecordingEventBus()
    state.skill_runner = skill_runner
    state.tools = []
    return state


# --- PipelineRunner.run ---


def test_pipeline_not_found_raises(tmp_path: Path) -> None:
    pipelines_dir = tmp_path / "pipelines"
    pipelines_dir.mkdir()
    runner = PipelineRunner(pipelines_dir)
    app_state = _make_app_state()
    with pytest.raises(FileNotFoundError):
        runner.run("missing", {}, app_state)


def test_skill_node_executes_and_returns_output(tmp_path: Path) -> None:
    pipelines_dir = _write_pipeline(
        tmp_path,
        """
        name: test_pipe
        nodes:
          - id: step1
            type: skill
            skill: my_skill
            arguments:
              key: value
        """,
    )
    runner = PipelineRunner(pipelines_dir)
    app_state = _make_app_state()
    result = runner.run("test_pipe", {}, app_state)

    assert result.status == "completed"
    assert result.node_results["step1"].status == "completed"
    assert result.node_results["step1"].output == "skill-output"
    app_state.skill_runner.execute_skill.assert_called_once_with(
        tool_name="my_skill",
        arguments={"key": "value"},
        session_id="sess-1",
    )


def test_template_inputs_substitution(tmp_path: Path) -> None:
    pipelines_dir = _write_pipeline(
        tmp_path,
        """
        name: test_pipe
        nodes:
          - id: step1
            type: skill
            skill: my_skill
            arguments:
              query: "{{inputs.topic}}"
        """,
    )
    runner = PipelineRunner(pipelines_dir)
    app_state = _make_app_state()
    runner.run("test_pipe", {"topic": "black holes"}, app_state)

    app_state.skill_runner.execute_skill.assert_called_once_with(
        tool_name="my_skill",
        arguments={"query": "black holes"},
        session_id="sess-1",
    )


def test_template_node_output_substitution(tmp_path: Path) -> None:
    pipelines_dir = _write_pipeline(
        tmp_path,
        """
        name: test_pipe
        nodes:
          - id: step1
            type: skill
            skill: first_skill
            arguments: {}
          - id: step2
            type: skill
            skill: second_skill
            arguments:
              prev: "{{nodes.step1.output}}"
            depends_on: [step1]
        """,
    )
    runner = PipelineRunner(pipelines_dir)
    app_state = _make_app_state()
    runner.run("test_pipe", {}, app_state)

    calls = app_state.skill_runner.execute_skill.call_args_list
    assert calls[1].kwargs["arguments"]["prev"] == "skill-output"


def test_failed_node_skips_dependents(tmp_path: Path) -> None:
    pipelines_dir = _write_pipeline(
        tmp_path,
        """
        name: test_pipe
        nodes:
          - id: step1
            type: skill
            skill: broken_skill
            arguments: {}
          - id: step2
            type: skill
            skill: next_skill
            arguments: {}
            depends_on: [step1]
        """,
    )
    runner = PipelineRunner(pipelines_dir)
    app_state = _make_app_state()
    app_state.skill_runner.execute_skill.side_effect = RuntimeError("boom")

    result = runner.run("test_pipe", {}, app_state)

    assert result.status == "failed"
    assert result.node_results["step1"].status == "failed"
    assert result.node_results["step2"].status == "skipped"


def test_independent_nodes_in_same_wave_both_run(tmp_path: Path) -> None:
    pipelines_dir = _write_pipeline(
        tmp_path,
        """
        name: test_pipe
        nodes:
          - id: step1
            type: skill
            skill: skill_a
            arguments: {}
          - id: step2
            type: skill
            skill: skill_b
            arguments: {}
        """,
    )
    runner = PipelineRunner(pipelines_dir)
    app_state = _make_app_state()
    result = runner.run("test_pipe", {}, app_state)

    assert result.status == "completed"
    assert result.node_results["step1"].status == "completed"
    assert result.node_results["step2"].status == "completed"
    assert app_state.skill_runner.execute_skill.call_count == 2  # noqa: PLR2004


def test_pipeline_events_published(tmp_path: Path) -> None:
    pipelines_dir = _write_pipeline(
        tmp_path,
        """
        name: test_pipe
        nodes:
          - id: step1
            type: skill
            skill: my_skill
            arguments: {}
        """,
    )
    runner = PipelineRunner(pipelines_dir)
    app_state = _make_app_state()
    runner.run("test_pipe", {}, app_state)

    types = [type(e) for e in app_state.event_bus.events]
    assert PipelineStarted in types
    assert PipelineNodeStarted in types
    assert PipelineNodeCompleted in types
    assert PipelineCompleted in types


def test_list_pipelines(tmp_path: Path) -> None:
    pipelines_dir = tmp_path / "pipelines"
    pipelines_dir.mkdir()
    (pipelines_dir / "pipe_a.yaml").write_text("name: pipe_a\nnodes: []")
    (pipelines_dir / "pipe_b.yaml").write_text("name: pipe_b\nnodes: []")
    runner = PipelineRunner(pipelines_dir)
    names = runner.list_pipelines()
    assert set(names) == {"pipe_a", "pipe_b"}


def test_list_pipelines_empty_when_dir_missing(tmp_path: Path) -> None:
    runner = PipelineRunner(tmp_path / "no_such_dir")
    assert runner.list_pipelines() == []
