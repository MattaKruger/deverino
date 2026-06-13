# Pipeline Runner + Logfire Observability — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add declarative DAG-based multi-agent pipelines with Logfire observability to Deverino.

**Architecture:** A `PipelineRunner` loads YAML pipeline definitions, topologically sorts nodes into execution waves, runs parallel nodes via `ThreadPoolExecutor`, and publishes typed events. A separate `logfire_subscriber.py` wires those events to Logfire spans, keeping the runner free of observability concerns.

**Tech Stack:** Python 3.12, PydanticAI, Logfire, ThreadPoolExecutor, PyYAML, Typer

---

## File Map

| Action | File | Responsibility |
|---|---|---|
| Modify | `harness_poc/core/events.py` | Add 4 new pipeline event types |
| Modify | `harness_poc/core/config.py` | Add `pipelines` path + `ObservabilityConfig` |
| Modify | `harness.yaml` | Add `paths.pipelines` + `observability` section |
| Create | `harness_poc/core/pipeline_runner.py` | DAG execution, parallelism, template rendering |
| Create | `harness_poc/core/logfire_subscriber.py` | EventBus → Logfire wiring |
| Modify | `harness_poc/app_factory.py` | Add `pipeline_runner` to `AppState`, wire Logfire |
| Modify | `harness_poc/cli.py` | Add `pipeline run` and `pipeline list` CLI commands |
| Create | `pipelines/research_and_write.yaml` | Example pipeline |
| Create | `tests/test_pipeline_runner.py` | Pipeline runner unit tests |
| Modify | `pyproject.toml` | Add `logfire` dependency |

---

## Task 1: Add logfire dependency

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add logfire to dependencies**

```bash
uv add "logfire[pydantic-ai]"
```

Expected: `pyproject.toml` updated, `uv.lock` updated, no import errors.

- [ ] **Step 2: Verify import works**

```bash
uv run python -c "import logfire; print(logfire.__version__)"
```

Expected: prints a version string.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: add logfire dependency"
```

---

## Task 2: Add pipeline events

**Files:**
- Modify: `harness_poc/core/events.py`
- Test: `tests/test_events.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_events.py`:

```python
from harness_poc.core.events import (
    EVENT_REGISTRY,
    PipelineCompleted,
    PipelineNodeCompleted,
    PipelineNodeStarted,
    PipelineStarted,
)


def test_pipeline_started_roundtrip() -> None:
    event = PipelineStarted(session_id="s1", pipeline_name="my-pipe", node_count=3)
    assert event.event_type == "PipelineStarted"
    restored = PipelineStarted.model_validate(event.model_dump())
    assert restored.pipeline_name == "my-pipe"
    assert restored.node_count == 3


def test_pipeline_node_started_roundtrip() -> None:
    event = PipelineNodeStarted(session_id="s1", node_id="web_research", node_type="agent")
    assert event.event_type == "PipelineNodeStarted"
    restored = PipelineNodeStarted.model_validate(event.model_dump())
    assert restored.node_id == "web_research"
    assert restored.node_type == "agent"


def test_pipeline_node_completed_roundtrip() -> None:
    event = PipelineNodeCompleted(
        session_id="s1", node_id="web_research", status="completed", output_preview="done"
    )
    restored = PipelineNodeCompleted.model_validate(event.model_dump())
    assert restored.status == "completed"


def test_pipeline_completed_roundtrip() -> None:
    event = PipelineCompleted(
        session_id="s1", pipeline_name="my-pipe", status="completed", duration_s=1.5
    )
    restored = PipelineCompleted.model_validate(event.model_dump())
    assert restored.duration_s == 1.5


def test_pipeline_events_in_registry() -> None:
    for name in ("PipelineStarted", "PipelineNodeStarted", "PipelineNodeCompleted", "PipelineCompleted"):
        assert name in EVENT_REGISTRY
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_events.py -v -k "pipeline"
```

Expected: `ImportError` — pipeline event classes not yet defined.

- [ ] **Step 3: Add pipeline event classes to events.py**

In `harness_poc/core/events.py`, add after the `SubAgentCompleted` class and before `EVENT_REGISTRY`:

```python
class PipelineStarted(BaseEvent):
    pipeline_name: str
    node_count: int


class PipelineNodeStarted(BaseEvent):
    node_id: str
    node_type: str  # "skill" | "agent"


class PipelineNodeCompleted(BaseEvent):
    node_id: str
    status: str  # "completed" | "failed" | "skipped"
    output_preview: str


class PipelineCompleted(BaseEvent):
    pipeline_name: str
    status: str  # "completed" | "failed"
    duration_s: float
```

Update `EVENT_REGISTRY` to include the four new types:

```python
EVENT_REGISTRY: dict[str, type[BaseEvent]] = {
    cls.__name__: cls  # type: ignore[misc]
    for cls in [
        AgentStarted,
        SkillCalled,
        SkillCompleted,
        GoalEvaluated,
        LLMTextEmitted,
        SubAgentDispatched,
        SubAgentCompleted,
        PipelineStarted,
        PipelineNodeStarted,
        PipelineNodeCompleted,
        PipelineCompleted,
    ]
}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_events.py -v -k "pipeline"
```

Expected: 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add harness_poc/core/events.py tests/test_events.py
git commit -m "feat: add pipeline event types to event hierarchy"
```

---

## Task 3: Add pipelines path and observability config

**Files:**
- Modify: `harness_poc/core/config.py`
- Modify: `harness.yaml`

- [ ] **Step 1: Add `ObservabilityConfig` and `pipelines` path to config.py**

Add `ObservabilityConfig` after `RuntimeConfig` in `harness_poc/core/config.py`:

```python
@dataclass(frozen=True, slots=True)
class ObservabilityConfig:
    logfire_enabled: bool
```

Add `pipelines: Path` to `HarnessPaths` after `workflows`:

```python
@dataclass(frozen=True, slots=True)
class HarnessPaths:
    soul: Path
    system_skills: Path
    project_skills: Path
    workflows: Path
    pipelines: Path
    personas: Path
```

Add `observability: ObservabilityConfig` to `HarnessConfig`:

```python
@dataclass(frozen=True, slots=True)
class HarnessConfig:
    project_root: Path
    config_path: Path
    paths: HarnessPaths
    runtime: RuntimeConfig
    observability: ObservabilityConfig
```

Update `HarnessConfig.load()` to parse the new fields. Replace the existing `paths = HarnessPaths(...)` block with:

```python
observability_raw = _mapping(raw.get("observability"), "observability")

paths = HarnessPaths(
    soul=_resolve_path(
        project_root,
        paths_raw.get("soul", "harness_poc/system_prompts/SOUL.md"),
    ),
    system_skills=_resolve_path(
        project_root,
        paths_raw.get("system_skills", "harness_poc/system_skills"),
    ),
    project_skills=_resolve_path(
        project_root, paths_raw.get("project_skills", "skills")
    ),
    workflows=_resolve_path(
        project_root, paths_raw.get("workflows", "workflows")
    ),
    pipelines=_resolve_path(
        project_root, paths_raw.get("pipelines", "pipelines")
    ),
    personas=_resolve_path(
        project_root, paths_raw.get("personas", "personas")
    ),
)
observability = ObservabilityConfig(
    logfire_enabled=bool(observability_raw.get("logfire", False)),
)
```

Update the return statement to include `observability`:

```python
return cls(
    project_root=project_root,
    config_path=resolved_config_path,
    paths=paths,
    runtime=runtime,
    observability=observability,
)
```

- [ ] **Step 2: Update harness.yaml**

Add `pipelines` under `paths` and a new `observability` section. Final `harness.yaml`:

```yaml
version: 1.1

paths:
  # Engine Paths
  soul: harness_poc/system_prompts/SOUL.md
  system_skills: harness_poc/system_skills

  # Workspace Paths
  project_skills: skills
  personas: personas
  workflows: workflows
  pipelines: pipelines

runtime:
  database_path: harness_poc/blackboard.db
  default_container_image: python:3.12-slim

observability:
  logfire: false   # set to true and export LOGFIRE_TOKEN to enable
```

- [ ] **Step 3: Verify config loads cleanly**

```bash
uv run harness-poc state show project
```

Expected: no errors, state printed normally.

- [ ] **Step 4: Commit**

```bash
git add harness_poc/core/config.py harness.yaml
git commit -m "feat: add pipelines path and observability config"
```

---

## Task 4: Implement PipelineRunner

**Files:**
- Create: `harness_poc/core/pipeline_runner.py`
- Create: `tests/test_pipeline_runner.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_pipeline_runner.py`:

```python
from __future__ import annotations

import textwrap
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from harness_poc.core.pipeline_runner import PipelineRunner, build_waves
from harness_poc.core.skill_context import SkillResult
from tests.helpers import RecordingEventBus


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
    assert len(waves) == 3
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
    assert len(waves) == 2
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


def _make_app_state(pipelines_dir: Path) -> MagicMock:
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
    app_state = _make_app_state(pipelines_dir)
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
    app_state = _make_app_state(pipelines_dir)
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
    app_state = _make_app_state(pipelines_dir)
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
    app_state = _make_app_state(pipelines_dir)
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
    app_state = _make_app_state(pipelines_dir)
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
    app_state = _make_app_state(pipelines_dir)
    result = runner.run("test_pipe", {}, app_state)

    assert result.status == "completed"
    assert result.node_results["step1"].status == "completed"
    assert result.node_results["step2"].status == "completed"
    assert app_state.skill_runner.execute_skill.call_count == 2


def test_pipeline_events_published(tmp_path: Path) -> None:
    from harness_poc.core.events import (
        PipelineCompleted,
        PipelineNodeCompleted,
        PipelineNodeStarted,
        PipelineStarted,
    )

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
    app_state = _make_app_state(pipelines_dir)
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_pipeline_runner.py -v
```

Expected: `ImportError` — `pipeline_runner` module not yet created.

- [ ] **Step 3: Create harness_poc/core/pipeline_runner.py**

```python
from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from harness_poc.core.events import (
    PipelineCompleted,
    PipelineNodeCompleted,
    PipelineNodeStarted,
    PipelineStarted,
)

if TYPE_CHECKING:
    from harness_poc.app_factory import AppState

_TEMPLATE = re.compile(r"{{\s*([^}]+?)\s*}}")


@dataclass
class PipelineNodeResult:
    node_id: str
    status: str  # "completed" | "failed" | "skipped"
    output: str
    artifacts: dict[str, Any] = field(default_factory=dict)


@dataclass
class PipelineRunResult:
    pipeline_name: str
    status: str  # "completed" | "failed"
    node_results: dict[str, PipelineNodeResult]
    duration_s: float


def build_waves(nodes: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Topologically sort nodes into execution waves (lists of concurrently-runnable nodes)."""
    node_map = {n["id"]: n for n in nodes}
    for node in nodes:
        for dep in node.get("depends_on", []):
            if dep not in node_map:
                msg = f"Node '{node['id']}' depends on unknown node '{dep}'"
                raise ValueError(msg)

    waves: list[list[dict[str, Any]]] = []
    remaining: set[str] = {n["id"] for n in nodes}

    while remaining:
        ready = {
            nid
            for nid in remaining
            if all(dep not in remaining for dep in node_map[nid].get("depends_on", []))
        }
        if not ready:
            msg = f"Circular dependency detected among nodes: {remaining}"
            raise ValueError(msg)
        waves.append([node_map[nid] for nid in ready])
        remaining -= ready

    return waves


class PipelineRunner:
    def __init__(self, pipelines_dir: Path) -> None:
        self._pipelines_dir = pipelines_dir

    def list_pipelines(self) -> list[str]:
        if not self._pipelines_dir.exists():
            return []
        return sorted(p.stem for p in self._pipelines_dir.glob("*.yaml"))

    def run(
        self,
        pipeline_name: str,
        inputs: dict[str, Any],
        app_state: AppState,
    ) -> PipelineRunResult:
        pipeline = self._load(pipeline_name)
        nodes: list[dict[str, Any]] = pipeline.get("nodes", [])
        waves = build_waves(nodes)

        start = time.monotonic()
        app_state.event_bus.publish(
            PipelineStarted(
                session_id=app_state.session_id,
                pipeline_name=pipeline_name,
                node_count=len(nodes),
            )
        )

        node_results: dict[str, PipelineNodeResult] = {}
        failed_ids: set[str] = set()

        for wave in waves:
            ready = []
            for node in wave:
                blocked = any(dep in failed_ids for dep in node.get("depends_on", []))
                if blocked:
                    node_results[node["id"]] = PipelineNodeResult(
                        node_id=node["id"], status="skipped", output=""
                    )
                else:
                    ready.append(node)

            if not ready:
                continue

            if len(ready) == 1:
                result = self._execute_node(ready[0], inputs, node_results, app_state)
                node_results[result.node_id] = result
                if result.status == "failed":
                    failed_ids.add(result.node_id)
            else:
                with ThreadPoolExecutor(max_workers=len(ready)) as executor:
                    futures = {
                        executor.submit(
                            self._execute_node, node, inputs, node_results, app_state
                        ): node["id"]
                        for node in ready
                    }
                    for future in as_completed(futures):
                        result = future.result()
                        node_results[result.node_id] = result
                        if result.status == "failed":
                            failed_ids.add(result.node_id)

        duration_s = time.monotonic() - start
        status = "failed" if failed_ids else "completed"
        app_state.event_bus.publish(
            PipelineCompleted(
                session_id=app_state.session_id,
                pipeline_name=pipeline_name,
                status=status,
                duration_s=duration_s,
            )
        )
        return PipelineRunResult(
            pipeline_name=pipeline_name,
            status=status,
            node_results=node_results,
            duration_s=duration_s,
        )

    def _execute_node(
        self,
        node: dict[str, Any],
        inputs: dict[str, Any],
        node_results: dict[str, PipelineNodeResult],
        app_state: AppState,
    ) -> PipelineNodeResult:
        node_id: str = node["id"]
        node_type: str = node["type"]

        app_state.event_bus.publish(
            PipelineNodeStarted(
                session_id=app_state.session_id,
                node_id=node_id,
                node_type=node_type,
            )
        )

        try:
            if node_type == "skill":
                output = self._run_skill_node(node, inputs, node_results, app_state)
            elif node_type == "agent":
                output = self._run_agent_node(node, inputs, node_results, app_state)
            else:
                msg = f"Unknown node type '{node_type}' for node '{node_id}'"
                raise ValueError(msg)
            node_result = PipelineNodeResult(node_id=node_id, status="completed", output=output)
        except Exception as exc:
            node_result = PipelineNodeResult(node_id=node_id, status="failed", output=str(exc))

        app_state.event_bus.publish(
            PipelineNodeCompleted(
                session_id=app_state.session_id,
                node_id=node_id,
                status=node_result.status,
                output_preview=node_result.output[:200],
            )
        )
        return node_result

    def _run_skill_node(
        self,
        node: dict[str, Any],
        inputs: dict[str, Any],
        node_results: dict[str, PipelineNodeResult],
        app_state: AppState,
    ) -> str:
        skill_name: str = node["skill"]
        raw_args: dict[str, Any] = node.get("arguments", {})
        rendered_args = _render_value(raw_args, inputs=inputs, node_results=node_results)
        result = app_state.skill_runner.execute_skill(
            tool_name=skill_name,
            arguments=rendered_args,
            session_id=app_state.session_id,
        )
        return str(result.content)

    def _run_agent_node(
        self,
        node: dict[str, Any],
        inputs: dict[str, Any],
        node_results: dict[str, PipelineNodeResult],
        app_state: AppState,
    ) -> str:
        import dataclasses

        from harness_poc.core.goal_runner import GoalRunner

        goal = _render_string(node["goal"], inputs=inputs, node_results=node_results)
        allowed_skills: list[str] | None = node.get("allowed_skills")

        if allowed_skills is not None:
            allowed = set(allowed_skills)
            filtered_tools = [
                t for t in app_state.tools if t.get("function", {}).get("name") in allowed
            ]
            effective_state = dataclasses.replace(app_state, tools=filtered_tools)
        else:
            effective_state = app_state

        run_result = GoalRunner().run(goal=goal, app_state=effective_state)
        return run_result.content

    def _load(self, pipeline_name: str) -> dict[str, Any]:
        path = self._pipelines_dir / f"{pipeline_name}.yaml"
        if not path.exists():
            msg = f"Pipeline not found: {pipeline_name}"
            raise FileNotFoundError(msg)
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            msg = f"Invalid pipeline YAML: {path}"
            raise TypeError(msg)
        return raw  # type: ignore[return-value]


def _render_value(
    value: object,
    *,
    inputs: dict[str, Any],
    node_results: dict[str, PipelineNodeResult],
) -> Any:  # noqa: ANN401
    if isinstance(value, str):
        return _render_string(value, inputs=inputs, node_results=node_results)
    if isinstance(value, dict):
        return {
            k: _render_value(v, inputs=inputs, node_results=node_results)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_render_value(item, inputs=inputs, node_results=node_results) for item in value]
    return value


def _render_string(
    value: str,
    *,
    inputs: dict[str, Any],
    node_results: dict[str, PipelineNodeResult],
) -> str:
    def replace(match: re.Match[str]) -> str:
        expr = match.group(1).strip()
        parts = expr.split(".")
        root = parts[0]
        if root == "inputs":
            key = ".".join(parts[1:])
            if key not in inputs:
                msg = f"Input key '{key}' not found"
                raise KeyError(msg)
            return str(inputs[key])
        if root == "nodes":
            if len(parts) < 2:  # noqa: PLR2004
                msg = f"Invalid node reference: '{expr}'"
                raise ValueError(msg)
            node_id = parts[1]
            if node_id not in node_results:
                msg = f"Node '{node_id}' output is not yet available"
                raise KeyError(msg)
            attr = parts[2] if len(parts) > 2 else "output"  # noqa: PLR2004
            if attr != "output":
                msg = f"Only '{{{{nodes.NODE.output}}}}' is supported, got '{expr}'"
                raise ValueError(msg)
            return node_results[node_id].output
        msg = f"Unknown template root '{root}' in '{{{{ {expr} }}}}'"
        raise ValueError(msg)

    return _TEMPLATE.sub(replace, value)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_pipeline_runner.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Run linter and type checker**

```bash
uv run ruff check harness_poc/core/pipeline_runner.py
uv run ty check
```

Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add harness_poc/core/pipeline_runner.py tests/test_pipeline_runner.py
git commit -m "feat: add PipelineRunner with DAG execution and wave-based parallelism"
```

---

## Task 5: Implement Logfire subscriber

**Files:**
- Create: `harness_poc/core/logfire_subscriber.py`

- [ ] **Step 1: Create logfire_subscriber.py**

```python
from __future__ import annotations

from typing import TYPE_CHECKING

import logfire

from harness_poc.core.events import (
    AgentStarted,
    GoalEvaluated,
    PipelineCompleted,
    PipelineNodeCompleted,
    PipelineNodeStarted,
    PipelineStarted,
    SkillCalled,
    SkillCompleted,
)

if TYPE_CHECKING:
    from harness_poc.core.event_bus import EventBus


def configure_logfire() -> None:
    logfire.configure()
    logfire.instrument_pydantic_ai()


def wire_logfire(event_bus: EventBus) -> None:
    """Subscribe Logfire handlers to the EventBus. Call configure_logfire() first."""
    event_bus.subscribe(PipelineStarted, _on_pipeline_started)
    event_bus.subscribe(PipelineNodeStarted, _on_node_started)
    event_bus.subscribe(PipelineNodeCompleted, _on_node_completed)
    event_bus.subscribe(PipelineCompleted, _on_pipeline_completed)
    event_bus.subscribe(AgentStarted, _on_agent_started)
    event_bus.subscribe(SkillCalled, _on_skill_called)
    event_bus.subscribe(SkillCompleted, _on_skill_completed)
    event_bus.subscribe(GoalEvaluated, _on_goal_evaluated)


def _on_pipeline_started(event: PipelineStarted) -> None:
    logfire.info(
        "pipeline started",
        pipeline_name=event.pipeline_name,
        node_count=event.node_count,
        session_id=event.session_id,
    )


def _on_node_started(event: PipelineNodeStarted) -> None:
    logfire.info(
        "pipeline node started",
        node_id=event.node_id,
        node_type=event.node_type,
        session_id=event.session_id,
    )


def _on_node_completed(event: PipelineNodeCompleted) -> None:
    logfire.info(
        "pipeline node completed",
        node_id=event.node_id,
        status=event.status,
        output_preview=event.output_preview,
        session_id=event.session_id,
    )


def _on_pipeline_completed(event: PipelineCompleted) -> None:
    logfire.info(
        "pipeline completed",
        pipeline_name=event.pipeline_name,
        status=event.status,
        duration_s=event.duration_s,
        session_id=event.session_id,
    )


def _on_agent_started(event: AgentStarted) -> None:
    logfire.info(
        "agent started",
        goal=event.goal,
        session_id=event.session_id,
    )


def _on_skill_called(event: SkillCalled) -> None:
    logfire.info(
        "skill called",
        tool_name=event.tool_name,
        session_id=event.session_id,
    )


def _on_skill_completed(event: SkillCompleted) -> None:
    logfire.info(
        "skill completed",
        tool_name=event.tool_name,
        status=event.status,
        session_id=event.session_id,
    )


def _on_goal_evaluated(event: GoalEvaluated) -> None:
    logfire.info(
        "goal evaluated",
        is_complete=event.is_complete,
        reasoning=event.reasoning[:200],
        session_id=event.session_id,
    )
```

- [ ] **Step 2: Verify import and lint**

```bash
uv run python -c "from harness_poc.core.logfire_subscriber import wire_logfire; print('ok')"
uv run ruff check harness_poc/core/logfire_subscriber.py
```

Expected: prints "ok", no lint errors.

- [ ] **Step 3: Commit**

```bash
git add harness_poc/core/logfire_subscriber.py
git commit -m "feat: add Logfire EventBus subscriber for pipeline and agent observability"
```

---

## Task 6: Wire PipelineRunner and Logfire into AppState

**Files:**
- Modify: `harness_poc/app_factory.py`

- [ ] **Step 1: Add pipeline_runner to AppState and wire Logfire in build_app_state**

In `harness_poc/app_factory.py`:

Add the import at the top:

```python
from harness_poc.core.pipeline_runner import PipelineRunner
```

Add `pipeline_runner: PipelineRunner` to `AppState` after `workflow_runner`:

```python
@dataclass(slots=True)
class AppState:
    session_id: str
    database: BlackboardDatabase
    config: HarnessConfig
    skill_runner: SkillRunner
    skill_scaffolder: SkillScaffolder
    workflow_runner: WorkflowRunner
    pipeline_runner: PipelineRunner
    llm_client: LLMClient
    pydantic_runtime: PydanticAgentRuntime
    pydantic_messages: list[ModelMessage]
    goal_decision_model: Model | None
    messages: list[Message]
    tools: list[dict[str, Any]]
    event_bus: EventBus
```

In `build_app_state()`, after `workflow_runner = WorkflowRunner(skill_runner)` add:

```python
pipeline_runner = PipelineRunner(config.paths.pipelines)
```

After `event_bus = EventBus(event_store)` add:

```python
if config.observability.logfire_enabled:
    from harness_poc.core.logfire_subscriber import configure_logfire, wire_logfire
    configure_logfire()
    wire_logfire(event_bus)
```

Add `pipeline_runner=pipeline_runner` to the `AppState(...)` constructor call, after `workflow_runner=workflow_runner`.

- [ ] **Step 2: Verify the app starts cleanly**

```bash
uv run harness-poc state show project
```

Expected: no errors.

- [ ] **Step 3: Run the full test suite**

```bash
uv run pytest -v
```

Expected: all existing tests pass plus new pipeline tests.

- [ ] **Step 4: Commit**

```bash
git add harness_poc/app_factory.py
git commit -m "feat: wire PipelineRunner and Logfire into AppState"
```

---

## Task 7: Add pipeline CLI commands

**Files:**
- Modify: `harness_poc/cli.py`

- [ ] **Step 1: Add pipeline_app sub-app and commands to cli.py**

After the `skill_app` Typer declaration (line 47), add:

```python
pipeline_app = typer.Typer(
    help="Run declarative DAG pipeline YAML files.",
    rich_markup_mode="rich",
)
```

After the existing `skill_create` command, add:

```python
@pipeline_app.command("list")
def pipeline_list() -> None:
    """List discovered pipeline YAML files."""
    app_state = _new_app_state()
    names = app_state.pipeline_runner.list_pipelines()
    if not names:
        console.print("[dim]No pipelines found.[/dim]")
        return
    for name in names:
        console.print(f"  {name}")


@pipeline_app.command("run")
def pipeline_run(
    name: Annotated[str, typer.Argument(help="Pipeline YAML name without .yaml.")],
    inputs: Annotated[
        list[str],
        typer.Option("--input", "-i", help="Input as key=value. Repeat for multiple inputs."),
    ] = [],  # noqa: B006
) -> None:
    """Run a pipeline and print the node results."""
    parsed_inputs: dict[str, str] = {}
    for item in inputs:
        if "=" not in item:
            print_error(f"Invalid --input format '{item}': expected key=value")
            raise typer.Exit(1)
        key, _, value = item.partition("=")
        parsed_inputs[key.strip()] = value.strip()

    app_state = _new_app_state()
    try:
        result = app_state.pipeline_runner.run(name, parsed_inputs, app_state)
    except FileNotFoundError as exc:
        print_error(str(exc))
        raise typer.Exit(1) from exc
    except Exception as exc:
        print_error(f"Pipeline failed: {exc}")
        raise typer.Exit(1) from exc

    status_style = {"completed": "green", "failed": "red"}
    color = status_style.get(result.status, "white")
    console.print(f"\n[{color}]Pipeline '{name}': {result.status}[/{color}] ({result.duration_s:.1f}s)\n")

    for node_id, node_result in result.node_results.items():
        node_color = {"completed": "green", "failed": "red", "skipped": "yellow"}.get(
            node_result.status, "white"
        )
        console.print(f"  [{node_color}]{node_id}: {node_result.status}[/{node_color}]")
        if node_result.output:
            console.print(f"    {node_result.output[:300]}")

    if result.status == "failed":
        raise typer.Exit(1)
```

At the bottom of the file, add the pipeline_app alongside the other sub-apps:

```python
app.add_typer(pipeline_app, name="pipeline")
```

- [ ] **Step 2: Verify CLI commands are discoverable**

```bash
uv run harness-poc pipeline --help
```

Expected: shows `list` and `run` commands.

```bash
uv run harness-poc pipeline list
```

Expected: prints "No pipelines found." (pipelines dir is empty).

- [ ] **Step 3: Run lint**

```bash
uv run ruff check harness_poc/cli.py
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add harness_poc/cli.py
git commit -m "feat: add pipeline list and pipeline run CLI commands"
```

---

## Task 8: Add example pipeline and end-to-end smoke test

**Files:**
- Create: `pipelines/research_and_write.yaml`

- [ ] **Step 1: Create pipelines directory and example pipeline**

```bash
mkdir -p pipelines
```

Create `pipelines/research_and_write.yaml`:

```yaml
name: research-and-write
description: |
  Research a topic using memory lookup and web search in parallel,
  then synthesize findings into a document.

inputs:
  topic: string

nodes:
  - id: memory_research
    type: skill
    skill: read_memory
    arguments:
      query: "{{inputs.topic}}"

  - id: synthesize
    type: agent
    goal: |
      Write a short summary document about: {{inputs.topic}}

      Available research from memory:
      {{nodes.memory_research.output}}

      Produce a clear, concise summary with key points.
    depends_on: [memory_research]
```

- [ ] **Step 2: Verify the pipeline appears in the list**

```bash
uv run harness-poc pipeline list
```

Expected: prints `research-and-write`.

- [ ] **Step 3: Run the full test suite one final time**

```bash
uv run pytest -v
uv run ruff check .
uv run ty check
```

Expected: all tests pass, no lint errors, no type errors.

- [ ] **Step 4: Commit**

```bash
git add pipelines/research_and_write.yaml
git commit -m "feat: add research-and-write example pipeline"
```
