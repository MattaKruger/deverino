from __future__ import annotations

import dataclasses
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import yaml

from harness_poc.core.events import (
    PipelineCompleted,
    PipelineNodeCompleted,
    PipelineNodeStarted,
    PipelineStarted,
)
from harness_poc.core.goal_runner import GoalRunner

if TYPE_CHECKING:
    from pathlib import Path

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

        if node_type not in ("skill", "agent"):
            msg = f"Unknown node type '{node_type}' for node '{node_id}'"
            raise ValueError(msg)

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
            else:
                output = self._run_agent_node(node, inputs, node_results, app_state)
            node_result = PipelineNodeResult(node_id=node_id, status="completed", output=output)
        except Exception as exc:  # noqa: BLE001
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
