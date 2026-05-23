from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

import yaml

if TYPE_CHECKING:
    from harness_poc.core.skills import SkillResult, SkillRunner


TEMPLATE_PATTERN = re.compile(r"{{\s*([^}]+?)\s*}}")


@dataclass(frozen=True, slots=True)
class WorkflowStateOutput:
    state_name: str
    skill_name: str
    result: SkillResult

    def to_dict(self) -> dict[str, Any]:
        return {
            "state_name": self.state_name,
            "skill_name": self.skill_name,
            "result": self.result.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class WorkflowRunResult:
    workflow_id: str
    workflow_name: str
    status: str
    outputs: list[WorkflowStateOutput] = field(default_factory=list)

    @property
    def final_content(self) -> str:
        if not self.outputs:
            return "Workflow completed without skill outputs."
        return self.outputs[-1].result.content

    def summary(self) -> str:
        state_lines = [
            f"- {output.state_name}: {output.skill_name} -> {output.result.status}"
            for output in self.outputs
        ]
        return "\n".join(
            [
                f"Workflow {self.workflow_name} completed with status: {self.status}",
                *state_lines,
                "",
                self.final_content,
            ],
        )


class WorkflowRunner:
    def __init__(self, skill_runner: SkillRunner) -> None:
        self.skill_runner = skill_runner
        self.config = skill_runner.config
        self.database = skill_runner.database

    def run(
        self,
        workflow_name: str,
        inputs: dict[str, Any],
        session_id: str,
    ) -> WorkflowRunResult:
        workflow = self._load_workflow(workflow_name)
        workflow_id = str(uuid.uuid4())
        states = _mapping(workflow.get("states"), "states")
        current_state = _first_state_name(states)
        outputs: list[WorkflowStateOutput] = []
        state_context: dict[str, Any] = {}
        container_config = _optional_mapping(workflow.get("container"), "container")
        container_name: str | None = None

        # Auto-spawn container if workflow declares one
        if container_config:
            spawn_result = self._spawn_container(
                container_config=container_config,
                workflow_id=workflow_id,
                session_id=session_id,
            )
            if spawn_result is not None:
                outputs.append(spawn_result)
                state_context["_spawn"] = spawn_result.result.to_dict()
                container_name = str(spawn_result.result.artifacts.get("container_name", ""))

        result_status = "completed"
        try:
            for _ in range(100):
                state = _mapping(states[current_state], f"states.{current_state}")
                if bool(state.get("terminal", False)):
                    break

                skill_name = _required_str(state.get("skill"), f"states.{current_state}.skill")
                raw_args = _mapping(state.get("args", {}), f"states.{current_state}.args")
                rendered_args = cast(
                    "dict[str, Any]",
                    self._render_value(raw_args, inputs=inputs, states=state_context),
                )
                result = self.skill_runner.execute_skill(
                    tool_name=skill_name,
                    arguments=rendered_args,
                    session_id=session_id,
                )
                output = WorkflowStateOutput(
                    state_name=current_state,
                    skill_name=skill_name,
                    result=result,
                )
                outputs.append(output)
                state_context[current_state] = result.to_dict()
                self.database.write_memory(
                    session_id=session_id,
                    key=f"workflow.{workflow_id}.{current_state}",
                    payload=output.to_dict(),
                )

                next_state = state.get("next")
                if next_state is None:
                    result_status = result.status
                    break
                current_state = _required_str(next_state, f"states.{current_state}.next")
            else:
                msg = f"Workflow {workflow_name} exceeded 100 states"
                raise RuntimeError(msg)
        finally:
            # Auto-destroy container on completion or failure
            if container_name:
                self._destroy_container(
                    container_name=container_name,
                    workflow_id=workflow_id,
                    session_id=session_id,
                )

        return WorkflowRunResult(
            workflow_id=workflow_id,
            workflow_name=workflow_name,
            status=result_status,
            outputs=outputs,
        )

    def _load_workflow(self, workflow_name: str) -> dict[str, Any]:
        workflow_path = self.config.paths.workflows / f"{workflow_name}.yaml"
        if not workflow_path.exists():
            msg = f"Workflow not found: {workflow_name}"
            raise FileNotFoundError(msg)
        workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
        if not isinstance(workflow, dict):
            msg = f"Invalid workflow YAML: {workflow_path}"
            raise TypeError(msg)
        return cast("dict[str, Any]", workflow)

    def _render_value(
        self,
        value: object,
        *,
        inputs: dict[str, Any],
        states: dict[str, Any],
    ) -> object:
        if isinstance(value, str):
            return self._render_string(value, inputs=inputs, states=states)

        if isinstance(value, dict):
            return {
                key: self._render_value(nested, inputs=inputs, states=states)
                for key, nested in value.items()
            }

        if isinstance(value, list):
            return [self._render_value(item, inputs=inputs, states=states) for item in value]

        return value

    def _render_string(
        self,
        value: str,
        *,
        inputs: dict[str, Any],
        states: dict[str, Any],
    ) -> str:
        def replace(match: re.Match[str]) -> str:
            expression = match.group(1).strip()
            resolved = _resolve_expression(expression, inputs=inputs, states=states)
            return str(resolved)

        return TEMPLATE_PATTERN.sub(replace, value)

    def _spawn_container(
        self,
        container_config: dict[str, Any],
        workflow_id: str,
        session_id: str,
    ) -> WorkflowStateOutput | None:
        image = str(container_config.get("image") or self.config.runtime.default_container_image)
        container_name = str(
            container_config.get("container_name") or f"harness-{workflow_id[:12]}"
        )
        spawn_args: dict[str, Any] = {
            "image": image,
            "container_name": container_name,
        }
        try:
            result = self.skill_runner.execute_skill(
                tool_name="container_spawn",
                arguments=spawn_args,
                session_id=session_id,
            )
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            print(f"Warning: container_spawn failed: {exc}")
            return None
        return WorkflowStateOutput(
            state_name="_spawn",
            skill_name="container_spawn",
            result=result,
        )

    def _destroy_container(
        self,
        container_name: str,
        workflow_id: str,
        session_id: str,
    ) -> None:
        del workflow_id
        try:
            self.skill_runner.execute_skill(
                tool_name="container_destroy",
                arguments={"container": container_name},
                session_id=session_id,
            )
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            print(f"Warning: container_destroy failed: {exc}")


def _resolve_expression(
    expression: str, *, inputs: dict[str, Any], states: dict[str, Any]
) -> object:
    parts = expression.split(".")
    if not parts:
        msg = "Template expression cannot be empty"
        raise ValueError(msg)

    if parts[0] == "inputs":
        current: Any = inputs
        remaining = parts[1:]
    elif parts[0] == "states":
        current = states
        remaining = parts[1:]
    else:
        msg = f"Unsupported template root: {parts[0]}"
        raise ValueError(msg)

    for part in remaining:
        if not isinstance(current, dict) or part not in current:
            msg = f"Could not resolve template expression: {expression}"
            raise KeyError(msg)
        current = current[part]

    return current


def _mapping(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        msg = f"Workflow section '{name}' must be a mapping"
        raise TypeError(msg)

    return cast("dict[str, Any]", value)


def _optional_mapping(value: object, name: str) -> dict[str, Any]:
    if value is None:
        return {}
    return _mapping(value, name)


def _first_state_name(states: dict[str, Any]) -> str:
    for state_name in states:
        return state_name
    msg = "Workflow must define at least one state"

    raise ValueError(msg)


def _required_str(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        msg = f"Workflow value '{name}' must be a non-empty string"
        raise TypeError(msg)

    return value
