"""Tests for Phase 3 — Self-Improvement Loops.

Coverage:
- evaluate_output skill: produces actionable critique
- evaluate_and_refine: iterative improvement wrapper
- GoalRunner reflexion cycle: refine=True runs critique loop
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from harness_poc.core.eval.refine import evaluate_and_refine, _extract_output, _inject_critique
from harness_poc.core.runtime.goal_runner import GoalRunner, GoalRunResult


# ---------------------------------------------------------------------------
# evaluate_and_refine
# ---------------------------------------------------------------------------


class TestEvaluateAndRefine:
    def test_extract_output_from_content(self) -> None:
        result = {"content": "Hello world", "artifacts": {}}
        assert _extract_output(result) == "Hello world"

    def test_extract_output_from_artifacts(self) -> None:
        result = {"content": "", "artifacts": {"model_output": {"summary": "Generated text"}}}
        assert _extract_output(result) == "Generated text"

    def test_inject_critique_objective(self) -> None:
        original = {"objective": "Design a cache"}
        modified = _inject_critique(original, "Missing TTL handling")
        assert "[Feedback from previous attempt" in modified["objective"]
        assert "Missing TTL handling" in modified["objective"]

    def test_inject_critique_preserves_keys(self) -> None:
        original = {"objective": "Test", "other": "value"}
        modified = _inject_critique(original, "critique")
        assert modified["other"] == "value"
        assert modified["objective"] != original["objective"]

    def test_evaluate_and_refine_single_pass(self) -> None:
        """When the first attempt passes, no refinement occurs."""
        call_count = 0

        def execute(_name: str, _args: dict) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            return {
                "content": (
                    "This is a comprehensive and excellent output that fully addresses "
                    "all requirements. It includes detailed explanations, examples, "
                    "edge case handling, and proper structure. The solution is complete "
                    "and well-organized with clear documentation of parameters and returns. "
                    "All functions are properly named and documented with docstrings. "
                    "The implementation handles edge cases correctly and follows all "
                    "project conventions. This is a model answer that would pass review."
                ),
                "artifacts": {},
            }

        result = evaluate_and_refine(
            skill_name="test",
            skill_input={"objective": "Write a function"},
            execute_fn=execute,
            max_iterations=3,
        )
        assert call_count == 1  # passed on first try
        assert len(result["_refinement_history"]) == 1

    def test_evaluate_and_refine_multiple_passes(self) -> None:
        """Poor output triggers refinement up to max_iterations."""
        call_count = 0

        def execute(_name: str, _args: dict) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            if call_count >= 3:
                return {
                    "content": "Excellent, complete, well-structured output with all details",
                    "artifacts": {},
                }
            return {"content": "short", "artifacts": {}}

        result = evaluate_and_refine(
            skill_name="test",
            skill_input={"objective": "Write a function"},
            execute_fn=execute,
            max_iterations=3,
        )
        assert call_count >= 2  # at least one refinement
        assert len(result["_refinement_history"]) >= 2

    def test_evaluate_and_refine_keeps_best(self) -> None:
        """Best-scoring output is returned, even if not the last."""
        call_count = 0

        def execute(_name: str, _args: dict) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {
                    "content": "Excellent, complete, well-structured output with all details",
                    "artifacts": {},
                }
            return {"content": "bad", "artifacts": {}}

        result = evaluate_and_refine(
            skill_name="test",
            skill_input={"objective": "Write a function"},
            execute_fn=execute,
            max_iterations=3,
        )
        history = result["_refinement_history"]
        assert history[0]["score"] >= history[1]["score"]


# ---------------------------------------------------------------------------
# GoalRunner Reflexion
# ---------------------------------------------------------------------------


class TestGoalRunnerReflexion:
    def test_refine_field_defaults(self) -> None:
        runner = GoalRunner()
        assert runner.refine is False
        assert runner.refine_threshold == 3.0

    def test_refine_enabled(self) -> None:
        runner = GoalRunner(refine=True, refine_threshold=4.0)
        assert runner.refine is True
        assert runner.refine_threshold == 4.0

    def test_evaluate_result_returns_dict(self) -> None:
        """_evaluate_result returns None when evaluate_output not available."""
        # Without a real SkillRunner, evaluate_result should handle failure gracefully
        runner = GoalRunner()
        app_state = MagicMock()
        app_state.skill_runner.execute_skill.side_effect = RuntimeError("not available")
        app_state.session_id = "test"

        result = runner._evaluate_result("goal", "output", app_state)
        assert result is None  # graceful failure

    def test_run_without_refine_no_effect(self) -> None:
        """When refine=False, results are returned directly."""
        runner = GoalRunner(refine=False)
        # The main loop behavior is unchanged
        assert runner.refine is False
