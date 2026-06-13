"""Tests for WorkflowOrchestrator — two-mode workflow pipeline.

Uses in-memory spies for ContextEngine and ExecutionEngine (no real
sandbox, no real subprocess) so tests run in milliseconds.
"""

from __future__ import annotations

from typing import Any

from harness_poc.v2.workflow_orchestrator import (
    WorkflowOrchestrator,
    _extract_traceback_lines,
)

# ---------------------------------------------------------------------------
# Test doubles (spies)
# ---------------------------------------------------------------------------

class ContextEngineSpy:
    """Records calls to ContextEngine for assertion."""

    def __init__(self) -> None:
        self.warm_up_calls: list[dict] = []
        self.materialize_calls: list[dict] = []
        self._next_event_id = 1

    def warm_up_context_from_failure(
        self,
        session_id: str,
        execution_error: dict[str, Any],
    ) -> dict[str, Any]:
        self.warm_up_calls.append(
            {"session_id": session_id, "execution_error": execution_error}
        )
        # Simulate constraint extraction based on error patterns
        constraints: list[dict[str, str]] = []
        stderr = execution_error.get("stderr", "")
        if "ModuleNotFoundError" in stderr:
            constraints.append(
                {"type": "missing_dependency", "detail": "Fake constraint"}
            )
        if "TypeError" in stderr:
            constraints.append(
                {"type": "type_constraint", "detail": "Fake constraint"}
            )
        event_id = self._next_event_id
        self._next_event_id += 1
        return {
            "discovered_constraints": constraints,
            "probe_event_id": event_id,
            "failure_source": {
                "exit_code": execution_error.get("exit_code"),
                "error_summary": stderr[:100] if stderr else "no error",
            },
        }

    def materialize_context_map(
        self,
        working_context: dict[str, Any],
        persona_id: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        self.materialize_calls.append(
            {"working_context": working_context, "persona_id": persona_id}
        )
        return {
            "persona_id": persona_id,
            "context_map": {"map_id": "test-map"},
            "rendered_context_map": "cycle: 99",
        }


class ExecutionEngineSpy:
    """Records calls to ExecutionEngine for assertion."""

    def __init__(self, gate_should_pass: bool = True) -> None:
        self.spawn_calls: list[dict] = []
        self.gate_calls: list[dict] = []
        self._gate_should_pass = gate_should_pass
        self._spawn_counter = 0
        # Simulated DB
        self._db = _FakeDB()

    def spawn_sub_agent(
        self,
        agent_type: str,
        task_payload: dict[str, Any],
        *,
        background: bool = False,
        session_id: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        self._spawn_counter += 1
        task_id = f"task-{self._spawn_counter:03d}"
        self.spawn_calls.append(
            {
                "agent_type": agent_type,
                "task_payload": task_payload,
                "background": background,
                "session_id": session_id,
            }
        )
        return {
            "task_id": task_id,
            "output_label": "completed",
            "summary": f"Agent {agent_type} completed task",
            "raw_output": {"result": "ok"},
            "metadata": {},
            "session_id": session_id or "auto",
            "background": background,
        }

    def execute_deterministic_gate(
        self,
        workspace_path: str,
        *,
        session_id: str | None = None,
        **kwargs: Any,
    ) -> bool:
        self.gate_calls.append(
            {"workspace_path": workspace_path, "session_id": session_id}
        )

        if self._gate_should_pass:
            self._db._materialized_maps["deverino"] = {
                "verified_state": {"gate_passed": True, "test_count": 42},
            }

        return self._gate_should_pass


class FailingExecutionEngineSpy(ExecutionEngineSpy):
    """ExecutionEngine that reports sub-agent failures."""

    def __init__(self) -> None:
        super().__init__()
        self._spawn_counter = 0

    def spawn_sub_agent(self, **kwargs: Any) -> dict[str, Any]:
        self._spawn_counter += 1
        task_id = f"task-{self._spawn_counter:03d}"
        self.spawn_calls.append(kwargs)
        return {
            "task_id": task_id,
            "output_label": "failed",
            "summary": "Agent failed",
            "raw_output": None,
            "metadata": {},
            "session_id": kwargs.get("session_id", "auto"),
            "background": kwargs.get("background", False),
        }


class GateFailingExecutionEngineSpy(ExecutionEngineSpy):
    """ExecutionEngine where the gate always fails."""

    def __init__(self) -> None:
        super().__init__(gate_should_pass=False)


class _FakeDB:
    """Minimal fake DB for ExecutionEngine._db access."""

    def __init__(self) -> None:
        self._materialized_maps: dict[str, dict] = {}

    def get_materialized_context_map(self, project_id: str) -> dict | None:
        return self._materialized_maps.get(project_id)

    def upsert_materialized_context_map(self, **kwargs: Any) -> None:
        self._materialized_maps[kwargs.get("project_id", "deverino")] = kwargs

    def append_context_event(self, **kwargs: Any) -> int:
        return 1


# ---------------------------------------------------------------------------
# Tests: Full pipeline
# ---------------------------------------------------------------------------

class TestFullPipeline:
    def test_all_three_steps_succeed(self):
        context = ContextEngineSpy()
        execution = ExecutionEngineSpy(gate_should_pass=True)

        orchestrator = WorkflowOrchestrator(
            context_engine=context,
            execution_engine=execution,
        )

        result = orchestrator.execute_workflow(
            spec={
                "tasks": [
                    {"agent_type": "code_reviewer", "objective": "Review code"},
                ],
            },
            persona_id="coder",
            probe_code="print('hello world')",
            workspace_path="/tmp/test-workspace",
        )

        assert result.probe is not None
        assert result.probe.success is True
        assert result.execution is not None
        assert result.execution.all_passed is True
        assert result.gate is not None
        assert result.gate.passed is True
        assert result.context_map_refreshed is True
        assert result.steps_completed == ["probe", "execution", "gate"]

    def test_probe_failure_warns_context(self):
        """When the probe fails, constraints are extracted and context is warmed."""
        context = ContextEngineSpy()
        execution = ExecutionEngineSpy()

        orchestrator = WorkflowOrchestrator(
            context_engine=context,
            execution_engine=execution,
        )

        result = orchestrator.execute_workflow(
            spec={"tasks": []},
            persona_id="coder",
            probe_code="import nonexistent_module\n",
            workspace_path="/tmp/test",
        )

        assert result.probe is not None
        assert result.probe.success is False
        assert len(result.probe.discovered_constraints) >= 1
        # ContextEngine.warm_up_context_from_failure was called
        assert len(context.warm_up_calls) == 1

    def test_skips_probe_when_none(self):
        context = ContextEngineSpy()
        execution = ExecutionEngineSpy()

        orchestrator = WorkflowOrchestrator(
            context_engine=context,
            execution_engine=execution,
        )

        result = orchestrator.execute_workflow(
            spec={
                "tasks": [
                    {"agent_type": "reviewer", "objective": "Review"},
                ],
            },
            persona_id="coder",
            probe_code=None,  # skip probe
            workspace_path="/tmp/test",
        )

        assert result.probe is None
        assert "probe" not in result.steps_completed
        assert "execution" in result.steps_completed

    def test_skips_gate_when_no_workspace(self):
        context = ContextEngineSpy()
        execution = ExecutionEngineSpy()

        orchestrator = WorkflowOrchestrator(
            context_engine=context,
            execution_engine=execution,
        )

        result = orchestrator.execute_workflow(
            spec={
                "tasks": [
                    {"agent_type": "reviewer", "objective": "Review"},
                ],
            },
            persona_id="coder",
            probe_code="print('ok')",
            workspace_path=None,  # skip gate
        )

        assert result.gate is None
        assert "gate" not in result.steps_completed
        assert "probe" in result.steps_completed


# ---------------------------------------------------------------------------
# Tests: Step #1 — Fail-Fast Probe
# ---------------------------------------------------------------------------

class TestFailFastProbe:
    def test_successful_code_returns_success(self):
        context = ContextEngineSpy()
        execution = ExecutionEngineSpy()

        orchestrator = WorkflowOrchestrator(
            context_engine=context,
            execution_engine=execution,
        )

        result = orchestrator.run_exploration_probe(
            code="x = 1 + 1\nprint(x)",
            session_id="sess-probe-1",
        )

        assert result.success is True
        assert result.exit_code == 0
        assert "2" in result.stdout

    def test_failing_code_extracts_constraints(self):
        context = ContextEngineSpy()
        execution = ExecutionEngineSpy()

        orchestrator = WorkflowOrchestrator(
            context_engine=context,
            execution_engine=execution,
        )

        result = orchestrator.run_exploration_probe(
            code="raise ValueError('something is wrong')",
            session_id="sess-probe-2",
        )

        assert result.success is False
        assert result.exit_code != 0
        assert "ValueError" in result.stderr

    def test_module_not_found_extracts_dependency_constraint(self):
        context = ContextEngineSpy()
        execution = ExecutionEngineSpy()

        orchestrator = WorkflowOrchestrator(
            context_engine=context,
            execution_engine=execution,
        )

        result = orchestrator.run_exploration_probe(
            code="import nonexistent_module_xyz",
            session_id="sess-probe-3",
        )

        assert result.success is False
        assert len(result.discovered_constraints) >= 1
        assert any(
            c["type"] == "missing_dependency" for c in result.discovered_constraints
        )

    def test_probe_timeout_handled(self):
        context = ContextEngineSpy()
        execution = ExecutionEngineSpy()

        orchestrator = WorkflowOrchestrator(
            context_engine=context,
            execution_engine=execution,
            sandbox_timeout_seconds=1,
        )

        result = orchestrator.run_exploration_probe(
            code="import time; time.sleep(10)",
            session_id="sess-probe-4",
        )

        assert result.success is False
        assert result.exit_code == -1  # timeout marker
        assert "timed out" in result.stderr.lower()


# ---------------------------------------------------------------------------
# Tests: Step #2 — Spec Execution
# ---------------------------------------------------------------------------

class TestSpecExecution:
    def test_spawns_agents_for_all_tasks(self):
        context = ContextEngineSpy()
        execution = ExecutionEngineSpy()

        orchestrator = WorkflowOrchestrator(
            context_engine=context,
            execution_engine=execution,
        )

        result = orchestrator.run_spec_execution(
            tasks=[
                {"agent_type": "code_reviewer", "objective": "Review"},
                {"agent_type": "data_validator", "objective": "Validate"},
                {"agent_type": "web_researcher", "objective": "Research"},
            ],
            session_id="sess-exec-1",
        )

        assert len(result.sub_agents) == 3
        assert result.all_passed is True
        assert result.failure_count == 0

    def test_agent_types_preserved(self):
        context = ContextEngineSpy()
        execution = ExecutionEngineSpy()

        orchestrator = WorkflowOrchestrator(
            context_engine=context,
            execution_engine=execution,
        )

        result = orchestrator.run_spec_execution(
            tasks=[
                {"agent_type": "code_reviewer", "objective": "Review"},
                {"agent_type": "data_validator", "objective": "Validate"},
            ],
            session_id="sess-exec-2",
        )

        types = [a.agent_type for a in result.sub_agents]
        assert "code_reviewer" in types
        assert "data_validator" in types

    def test_counts_failures_correctly(self):
        context = ContextEngineSpy()
        execution = FailingExecutionEngineSpy()

        orchestrator = WorkflowOrchestrator(
            context_engine=context,
            execution_engine=execution,
        )

        result = orchestrator.run_spec_execution(
            tasks=[
                {"agent_type": "reviewer", "objective": "Task 1"},
                {"agent_type": "reviewer", "objective": "Task 2"},
            ],
            session_id="sess-exec-3",
        )

        assert result.all_passed is False
        assert result.failure_count == 2

    def test_background_tasks_marked(self):
        context = ContextEngineSpy()
        execution = ExecutionEngineSpy()

        orchestrator = WorkflowOrchestrator(
            context_engine=context,
            execution_engine=execution,
        )

        result = orchestrator.run_spec_execution(
            tasks=[
                {"agent_type": "coder", "objective": "Foreground task"},
                {"agent_type": "coder", "objective": "Background task", "background": True},
            ],
            session_id="sess-exec-4",
        )

        bg_agents = [a for a in result.sub_agents if a.background]
        assert len(bg_agents) == 1

    def test_empty_tasks_returns_empty_result(self):
        context = ContextEngineSpy()
        execution = ExecutionEngineSpy()

        orchestrator = WorkflowOrchestrator(
            context_engine=context,
            execution_engine=execution,
        )

        result = orchestrator.run_spec_execution(
            tasks=[],
            session_id="sess-exec-5",
        )

        assert len(result.sub_agents) == 0
        assert result.all_passed is True


# ---------------------------------------------------------------------------
# Tests: Step #3 — Review Gate
# ---------------------------------------------------------------------------

class TestReviewGate:
    def test_gate_pass_returns_true(self):
        context = ContextEngineSpy()
        execution = ExecutionEngineSpy(gate_should_pass=True)

        orchestrator = WorkflowOrchestrator(
            context_engine=context,
            execution_engine=execution,
        )

        result = orchestrator.run_review_gate(
            workspace_path="/tmp/test",
            session_id="sess-gate-1",
        )

        assert result.passed is True
        assert result.test_count == 42

    def test_gate_fail_returns_false(self):
        context = ContextEngineSpy()
        execution = GateFailingExecutionEngineSpy()

        orchestrator = WorkflowOrchestrator(
            context_engine=context,
            execution_engine=execution,
        )

        result = orchestrator.run_review_gate(
            workspace_path="/tmp/test",
            session_id="sess-gate-2",
        )

        assert result.passed is False

    def test_gate_pass_triggers_context_refresh_in_pipeline(self):
        """In the full pipeline, gate pass → context_map_refreshed = True."""
        context = ContextEngineSpy()
        execution = ExecutionEngineSpy(gate_should_pass=True)

        orchestrator = WorkflowOrchestrator(
            context_engine=context,
            execution_engine=execution,
        )

        result = orchestrator.execute_workflow(
            spec={"tasks": []},
            persona_id="coder",
            probe_code="print('ok')",
            workspace_path="/tmp/test",
        )

        assert result.gate is not None
        assert result.gate.passed is True
        assert result.context_map_refreshed is True
        # ContextEngine.materialize_context_map was called for refresh
        assert len(context.materialize_calls) == 1

    def test_gate_fail_does_not_refresh_context(self):
        """Gate failure → context_map_refreshed stays False."""
        context = ContextEngineSpy()
        execution = GateFailingExecutionEngineSpy()

        orchestrator = WorkflowOrchestrator(
            context_engine=context,
            execution_engine=execution,
        )

        result = orchestrator.execute_workflow(
            spec={"tasks": []},
            persona_id="coder",
            probe_code="print('ok')",
            workspace_path="/tmp/test",
        )

        assert result.gate is not None
        assert result.gate.passed is False
        assert result.context_map_refreshed is False
        # ContextEngine.materialize_context_map was NOT called
        assert len(context.materialize_calls) == 0


# ---------------------------------------------------------------------------
# Tests: _extract_traceback_lines
# ---------------------------------------------------------------------------

class TestExtractTracebackLines:
    def test_extracts_traceback_entries(self):
        stderr = (
            "Traceback (most recent call last):\n"
            '  File "test.py", line 3, in <module>\n'
            "    import missing\n"
            "ModuleNotFoundError: No module named 'missing'\n"
        )
        lines = _extract_traceback_lines(stderr)
        assert len(lines) == 4
        assert "Traceback" in lines[0]
        assert "ModuleNotFoundError" in lines[3]

    def test_returns_empty_for_empty_input(self):
        assert _extract_traceback_lines("") == []

    def test_truncates_to_last_20(self):
        stderr = "\n".join(f'  File "file{i}.py", line 1' for i in range(30))
        lines = _extract_traceback_lines(stderr)
        assert len(lines) == 20


# ---------------------------------------------------------------------------
# Tests: Integration — probe failure → execution still proceeds
# ---------------------------------------------------------------------------

class TestIntegrationFlows:
    def test_probe_failure_does_not_block_execution(self):
        """Even if the probe fails, spec execution still runs."""
        context = ContextEngineSpy()
        execution = ExecutionEngineSpy()

        orchestrator = WorkflowOrchestrator(
            context_engine=context,
            execution_engine=execution,
        )

        result = orchestrator.execute_workflow(
            spec={
                "tasks": [
                    {"agent_type": "reviewer", "objective": "Review"},
                ],
            },
            persona_id="coder",
            probe_code="raise RuntimeError('probe failed')",
            workspace_path="/tmp/test",
        )

        assert result.probe.success is False
        assert result.execution is not None
        assert result.execution.all_passed is True
        assert "probe" in result.steps_completed
        assert "execution" in result.steps_completed
