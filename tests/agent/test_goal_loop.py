"""Agent-layer tests: full GoalRunner sessions with mock LLM.

These tests validate ReAct loop behaviour, skill sequencing, stuck
detection, context window construction, and budget enforcement.
"""

# ruff: noqa: ANN201, FBT003

from tests.agent.harness import SessionHarness
from tests.helpers import (
    evaluate_goal_response,
    text_response,
    tool_call_response,
)


def test_completes_on_direct_evaluate_goal():
    """The simplest possible session: model responds with evaluate_goal immediately."""
    harness = SessionHarness.build([
        evaluate_goal_response(True, "Task finished.", "Result: done."),
    ])
    harness.run("test goal")
    harness.assert_completed()
    harness.assert_final_answer_contains("Result: done")


def test_calls_skill_then_completes():
    """Model calls a skill, sees the result, then evaluates as complete."""
    harness = SessionHarness.build([
        tool_call_response("read_memory", {"memory_key": "test"}),
        evaluate_goal_response(True, "Read memory, all done.", "Final output."),
    ])
    harness.run("summarise state")
    harness.assert_skill_called("read_memory")
    harness.assert_completed()


def test_text_response_without_tool_call():
    """Text responses should be recorded as LLMTextEmitted and loop continues."""
    harness = SessionHarness.build([
        text_response("Let me think about this..."),
        evaluate_goal_response(True, "Thought about it.", "Answer."),
    ])
    harness.run("think")
    harness.assert_completed()
    assert len(harness.all_events) >= 3  # AgentStarted + LLMTextEmitted + GoalEvaluated


def test_iteration_budget_exhausted():
    """Loop should stop when max_iterations is reached."""
    harness = SessionHarness.build(
        [tool_call_response("read_memory", {"memory_key": "x"})],
        max_iterations=3,
    )
    harness.run("never complete")
    harness.assert_budget_exhausted()
    assert len(harness.skill_calls) == 3


def test_skill_error_does_not_crash_loop():
    """A failing skill should be recorded as error and the loop continues."""
    harness = SessionHarness.build([
        tool_call_response("nonexistent_skill", {}),
        evaluate_goal_response(True, "Handled the error.", "Recovered."),
    ])
    harness.run("test error handling")
    harness.assert_skill_called("nonexistent_skill")
    harness.assert_completed()
