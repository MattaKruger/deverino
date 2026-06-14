"""Tests for deterministic workflow and pipeline YAML files.

Validates:
  1. All workflow YAMLs in workflows/ parse correctly
  2. All pipeline YAMLs in pipelines/ parse correctly  
  3. WorkflowRunner integration with spy SkillRunner
  4. PipelineRunner topological sort (build_waves)
  5. Template interpolation in workflow/pipeline contexts
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest
import yaml

from harness_poc.core.execution.pipeline_runner import (
    PipelineRunResult,
    PipelineRunner,
    build_waves,
)
from harness_poc.core.execution.workflow_runner import (
    WorkflowRunner,
    WorkflowRunResult,
)
from harness_poc.core.skills import SkillResult

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS_DIR = PROJECT_ROOT / "workflows"
PIPELINES_DIR = PROJECT_ROOT / "pipelines"
SPECS_DIR = PROJECT_ROOT / "specs"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def workflow_paths() -> list[Path]:
    files = sorted(WORKFLOWS_DIR.glob("*.yaml"))
    if not files:
        pytest.skip("No workflow YAML files found")
    return files


@pytest.fixture
def pipeline_paths() -> list[Path]:
    files = sorted(PIPELINES_DIR.glob("*.yaml"))
    if not files:
        pytest.skip("No pipeline YAML files found")
    return files


@pytest.fixture
def spec_paths() -> list[Path]:
    files = sorted(SPECS_DIR.glob("*.yaml"))
    if not files:
        pytest.skip("No spec YAML files found")
    return files


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class SkillRunnerSpy:
    """Records every execute_skill call — no real execution."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self._next_status = "success"
        self._next_content = ""

    def execute_skill(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        session_id: str,
        **kwargs: Any,
    ) -> SkillResult:
        self.calls.append(
            {
                "tool_name": tool_name,
                "arguments": dict(arguments),
                "session_id": session_id,
            }
        )
        content = self._next_content or f"Executed {tool_name}"
        return SkillResult(status=self._next_status, content=content)

    @property
    def database(self) -> Any:
        class FakeDB:
            def write_memory(self, *args: Any, **kwargs: Any) -> None:
                pass
        return FakeDB()

    @property
    def config(self) -> Any:
        class FakeConfig:
            class Paths:
                workflows = WORKFLOWS_DIR

            paths = Paths()
        return FakeConfig()


class AppStateSpy:
    """Minimal AppState double for PipelineRunner tests."""

    def __init__(self, session_id: str = "test-session") -> None:
        self.session_id = session_id
        self.skill_runner = SkillRunnerSpy()
        self.tools: list[dict[str, Any]] = []
        self.event_bus = _EventBusSpy()

    def __dataclass_replace__(self, **kwargs: Any) -> AppStateSpy:
        for k, v in kwargs.items():
            setattr(self, k, v)
        return self


class _EventBusSpy:
    def publish(self, event_type: Any, payload: Any = None) -> None:
        pass


# ===================================================================
# 1. YAML VALIDATION
# ===================================================================


class TestWorkflowYaml:
    """Validate that every workflow YAML is structurally correct."""

    def test_all_workflows_parse(self, workflow_paths: list[Path]) -> None:
        for path in workflow_paths:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            assert isinstance(raw, dict), f"{path.name}: expected a mapping"
            assert "states" in raw, f"{path.name}: missing 'states' key"
            assert isinstance(raw["states"], dict), f"{path.name}: 'states' must be a mapping"
            assert len(raw["states"]) >= 1, f"{path.name}: must define at least one state"

    def test_every_state_has_skill(self, workflow_paths: list[Path]) -> None:
        for path in workflow_paths:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            states: dict = raw["states"]
            for name, state in states.items():
                assert isinstance(state, dict), f"{path.name}: state '{name}' must be a mapping"
                assert "skill" in state, f"{path.name}: state '{name}' missing 'skill'"
                assert isinstance(state["skill"], str), f"{path.name}: state '{name}'.skill must be a string"

    def test_workflow_has_terminal(self, workflow_paths: list[Path]) -> None:
        for path in workflow_paths:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            states: dict = raw["states"]
            terminal_states = [
                name for name, s in states.items()
                if s.get("terminal", False)
            ]
            assert terminal_states, f"{path.name}: no terminal state found"

    def test_state_transitions_are_valid(self, workflow_paths: list[Path]) -> None:
        for path in workflow_paths:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            states: dict = raw["states"]
            state_names = set(states)
            for name, state in states.items():
                if state.get("terminal", False):
                    assert "next" not in state, (
                        f"{path.name}: terminal state '{name}' should not have 'next'"
                    )
                elif "next" in state:
                    assert state["next"] in state_names, (
                        f"{path.name}: state '{name}' references unknown next state '{state['next']}'"
                    )


class TestPipelineYaml:
    """Validate that every pipeline YAML is structurally correct."""

    def test_all_pipelines_parse(self, pipeline_paths: list[Path]) -> None:
        for path in pipeline_paths:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            assert isinstance(raw, dict), f"{path.name}: expected a mapping"
            assert "nodes" in raw, f"{path.name}: missing 'nodes' key"
            assert isinstance(raw["nodes"], list), f"{path.name}: 'nodes' must be a list"
            assert len(raw["nodes"]) >= 1, f"{path.name}: must define at least one node"

    def test_every_node_has_id_and_type(self, pipeline_paths: list[Path]) -> None:
        for path in pipeline_paths:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            for node in raw["nodes"]:
                assert "id" in node, f"{path.name}: node missing 'id'"
                assert "type" in node, f"{path.name}: node '{node.get('id', '?')}' missing 'type'"
                assert node["type"] in ("skill", "agent"), (
                    f"{path.name}: node '{node['id']}' has invalid type '{node['type']}'"
                )

    def test_skill_nodes_have_skill_field(self, pipeline_paths: list[Path]) -> None:
        for path in pipeline_paths:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            for node in raw["nodes"]:
                if node["type"] == "skill":
                    assert "skill" in node, (
                        f"{path.name}: skill node '{node.get('id', '?')}' missing 'skill' field"
                    )

    def test_agent_nodes_have_goal_field(self, pipeline_paths: list[Path]) -> None:
        for path in pipeline_paths:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            for node in raw["nodes"]:
                if node["type"] == "agent":
                    assert "goal" in node, (
                        f"{path.name}: agent node '{node.get('id', '?')}' missing 'goal' field"
                    )

    def test_unique_node_ids(self, pipeline_paths: list[Path]) -> None:
        for path in pipeline_paths:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            ids = [n["id"] for n in raw["nodes"]]
            assert len(ids) == len(set(ids)), f"{path.name}: duplicate node IDs: {ids}"

    def test_depends_on_references_valid(self, pipeline_paths: list[Path]) -> None:
        for path in pipeline_paths:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            ids = {n["id"] for n in raw["nodes"]}
            for node in raw["nodes"]:
                for dep in node.get("depends_on", []):
                    assert dep in ids, (
                        f"{path.name}: node '{node['id']}' depends on unknown node '{dep}'"
                    )


class TestSpecYaml:
    """Validate that spec YAMLs are structurally correct."""

    def test_all_specs_parse(self, spec_paths: list[Path]) -> None:
        for path in spec_paths:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            assert isinstance(raw, dict), f"{path.name}: expected a mapping"

    def test_spec_has_probe_or_tasks(self, spec_paths: list[Path]) -> None:
        for path in spec_paths:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            has_probe = "probe" in raw and raw["probe"]
            has_tasks = "tasks" in raw and raw["tasks"]
            assert has_probe or has_tasks, f"{path.name}: must have 'probe' or 'tasks'"

    def test_spec_tasks_have_agent_type_and_objective(self, spec_paths: list[Path]) -> None:
        for path in spec_paths:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            for task in raw.get("tasks", []):
                assert "agent_type" in task, f"{path.name}: task missing 'agent_type'"
                assert "objective" in task, f"{path.name}: task missing 'objective'"


# ===================================================================
# 2. PIPELINE RUNNER — build_waves TOPOLOGICAL SORT
# ===================================================================


class TestBuildWaves:
    """Unit tests for the topological sort used by PipelineRunner."""

    def test_single_node(self) -> None:
        nodes = [{"id": "a", "type": "skill", "skill": "web_search"}]
        waves = build_waves(nodes)
        assert waves == [[nodes[0]]]

    def test_linear_chain(self) -> None:
        nodes = [
            {"id": "a", "type": "skill", "skill": "web_search"},
            {"id": "b", "type": "agent", "goal": "review", "depends_on": ["a"]},
            {"id": "c", "type": "agent", "goal": "report", "depends_on": ["b"]},
        ]
        waves = build_waves(nodes)
        assert len(waves) == 3
        assert len(waves[0]) == 1 and waves[0][0]["id"] == "a"
        assert len(waves[1]) == 1 and waves[1][0]["id"] == "b"
        assert len(waves[2]) == 1 and waves[2][0]["id"] == "c"

    def test_fan_out(self) -> None:
        """A -> B, C (parallel)."""
        nodes = [
            {"id": "a", "type": "skill", "skill": "search"},
            {"id": "b", "type": "agent", "goal": "review", "depends_on": ["a"]},
            {"id": "c", "type": "agent", "goal": "audit", "depends_on": ["a"]},
        ]
        waves = build_waves(nodes)
        assert len(waves) == 2
        assert len(waves[0]) == 1 and waves[0][0]["id"] == "a"
        assert len(waves[1]) == 2  # b and c run in parallel

    def test_fan_in(self) -> None:
        """A, B (parallel) -> C."""
        nodes = [
            {"id": "a", "type": "skill", "skill": "search"},
            {"id": "b", "type": "skill", "skill": "web_search"},
            {"id": "c", "type": "agent", "goal": "synth", "depends_on": ["a", "b"]},
        ]
        waves = build_waves(nodes)
        assert len(waves) == 2
        assert len(waves[0]) == 2  # a and b in parallel
        assert len(waves[1]) == 1 and waves[1][0]["id"] == "c"

    def test_diamond(self) -> None:
        """A -> B, C -> D."""
        nodes = [
            {"id": "a", "type": "skill", "skill": "search"},
            {"id": "b", "type": "agent", "goal": "r1", "depends_on": ["a"]},
            {"id": "c", "type": "agent", "goal": "r2", "depends_on": ["a"]},
            {"id": "d", "type": "agent", "goal": "merge", "depends_on": ["b", "c"]},
        ]
        waves = build_waves(nodes)
        assert len(waves) == 3
        assert len(waves[0]) == 1 and waves[0][0]["id"] == "a"
        assert len(waves[1]) == 2  # b, c parallel
        assert len(waves[2]) == 1 and waves[2][0]["id"] == "d"

    def test_no_dependencies(self) -> None:
        """All nodes run in parallel in a single wave."""
        nodes = [
            {"id": "a", "type": "skill", "skill": "s1"},
            {"id": "b", "type": "skill", "skill": "s2"},
            {"id": "c", "type": "skill", "skill": "s3"},
        ]
        waves = build_waves(nodes)
        assert len(waves) == 1
        assert len(waves[0]) == 3

    def test_circular_dependency_raises(self) -> None:
        nodes = [
            {"id": "a", "depends_on": ["b"]},
            {"id": "b", "depends_on": ["a"]},
        ]
        with pytest.raises(ValueError, match="Circular"):
            build_waves(nodes)

    def test_unknown_dependency_raises(self) -> None:
        nodes = [
            {"id": "a", "depends_on": ["nonexistent"]},
        ]
        with pytest.raises(ValueError, match="unknown"):
            build_waves(nodes)


# ===================================================================
# 3. WORKFLOW RUNNER INTEGRATION TESTS
# ===================================================================


class TestWorkflowRunnerIntegration:
    """Run workflows through the WorkflowRunner with a spy SkillRunner."""

    def _run_workflow(
        self, name: str, objective: str = "test objective",
    ) -> WorkflowRunResult:
        runner = WorkflowRunner(SkillRunnerSpy())  # type: ignore[arg-type]
        return runner.run(
            workflow_name=name,
            inputs={"objective": objective},
            session_id="test-session",
        )

    def test_code_review_flow_parses_and_runs(self) -> None:
        result = self._run_workflow("code-review-flow")
        assert result.status == "success" or result.status == "completed"
        assert len(result.outputs) >= 1

    def test_research_and_observe_parses_and_runs(self) -> None:
        result = self._run_workflow("research-and-observe", "how does the materializer work")
        assert len(result.outputs) >= 1

    def test_index_and_reflect_parses_and_runs(self) -> None:
        result = self._run_workflow("index-and-reflect", "index docs directory")
        assert len(result.outputs) >= 1

    def test_workflow_outputs_contain_skill_names(self) -> None:
        result = self._run_workflow("code-review-flow")
        skill_names = [o.skill_name for o in result.outputs]
        assert "semble_search" in skill_names
        assert "delegate_task" in skill_names

    def test_workflow_passes_inputs_to_states(self) -> None:
        spy = SkillRunnerSpy()
        runner = WorkflowRunner(spy)  # type: ignore[arg-type]
        runner.run(
            workflow_name="code-review-flow",
            inputs={"objective": "review the wiring module"},
            session_id="test-session",
        )
        # The first call should be semble_search with the objective
        assert len(spy.calls) >= 1
        first_call = spy.calls[0]
        assert first_call["tool_name"] == "semble_search"
        args = first_call["arguments"]
        assert "review the wiring module" in str(args)


# ===================================================================
# 4. PIPELINE RUNNER INTEGRATION TESTS (with real YAML)
# ===================================================================


class TestPipelineRunnerIntegration:
    """Run actual pipeline YAMLs through the PipelineRunner with a spy."""

    def _make_runner(self) -> PipelineRunner:
        return PipelineRunner(PIPELINES_DIR)

    def _make_app_state(self) -> AppStateSpy:
        return AppStateSpy()

    def test_parallel_review_parses_and_builds_waves(self) -> None:
        runner = self._make_runner()
        pipeline = runner._load("parallel-review")  # type: ignore[arg-type]
        nodes = pipeline["nodes"]
        waves = build_waves(nodes)
        # First wave: 3 parallel nodes (coder, reviewer, security)
        assert len(waves[0]) == 3
        # Second wave: 1 node (aggregate)
        assert len(waves) == 2
        assert waves[1][0]["id"] == "aggregate"

    def test_search_and_research_parses_and_builds_waves(self) -> None:
        runner = self._make_runner()
        pipeline = runner._load("search-and-research")  # type: ignore[arg-type]
        nodes = pipeline["nodes"]
        waves = build_waves(nodes)
        # First wave: 2 parallel nodes (codebase search + web search)
        assert len(waves[0]) == 2
        # Second wave: 1 node (synthesize)
        assert len(waves) == 2
        assert waves[1][0]["id"] == "synthesize"

    def test_list_pipelines(self) -> None:
        runner = self._make_runner()
        names = runner.list_pipelines()
        assert "parallel-review" in names
        assert "search-and-research" in names
