"""Tests for GoalRunner, database event methods, evaluate_goal skill, and CLI/REPL integration."""

# ruff: noqa: FBT003, PLC0415

from __future__ import annotations

from typing import TYPE_CHECKING

from harness_poc.app_factory import AppState, build_app_state
from harness_poc.core.events import AgentStarted, SkillCompleted
from harness_poc.core.runtime import GoalRunner
from tests.helpers import (
    _mock_goal_model,
    evaluate_goal_response,
    tool_call_response,
)

if TYPE_CHECKING:
    import pytest

    from harness_poc.core.runtime import LLMResponse

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_app_state(
    mock_responses: list[LLMResponse] | None = None,
) -> AppState:
    """Build an AppState with an in-memory database and optional mock LLM."""
    state = build_app_state()
    if mock_responses is not None:
        state.goal_decision_model = _mock_goal_model(mock_responses)
    return state


# ---------------------------------------------------------------------------
# evaluate_goal skill
# ---------------------------------------------------------------------------


def test_evaluate_goal_skill_registered() -> None:
    state = _make_app_state()
    tools = state.skill_runner.discover_skills()
    names = {tool["function"]["name"] for tool in tools if isinstance(tool.get("function"), dict)}
    assert "evaluate_goal" in names


def test_review_work_skill_executes() -> None:
    state = _make_app_state()
    state.database.write_memory(state.session_id, "candidate", {"summary": "ok"})

    result = state.skill_runner.execute_skill(
        tool_name="review_work",
        arguments={"objective": "Review candidate", "memory_key": "candidate"},
        session_id=state.session_id,
    )

    assert result.status == "success"
    assert "candidate" in result.content


# ---------------------------------------------------------------------------
# GoalRunner loop behavior (mock LLM)
# ---------------------------------------------------------------------------


def test_completed_generation_goal_prefers_final_answer() -> None:
    state = _make_app_state([
        evaluate_goal_response(
            True,
            "The commit message has been generated.",
            "feat: migrate goal runner to pydantic-ai",
        )
    ])
    runner = GoalRunner(max_iterations=10)

    result = runner.run("generate a commit message", state)

    assert result.status == "completed"
    assert result.content == "feat: migrate goal runner to pydantic-ai"


def test_completed_generation_goal_uses_latest_artifact_for_meta_reasoning() -> None:
    state = _make_app_state([
        tool_call_response("read_memory", {"memory_key": "commit_message"}),
        evaluate_goal_response(
            True,
            "The delegate_task skill returned a comprehensive commit message.",
        ),
    ])
    state.database.write_memory(
        state.session_id,
        "commit_message",
        {"summary": "feat: migrate goal runner to pydantic-ai"},
    )
    runner = GoalRunner(max_iterations=10)

    result = runner.run("generate a commit message", state)

    assert result.status == "completed"
    assert result.content == "feat: migrate goal runner to pydantic-ai"


def test_continues_on_evaluate_goal_false() -> None:
    state = _make_app_state([
        evaluate_goal_response(False, "Need more work."),
        evaluate_goal_response(True, "Now done."),
    ])
    runner = GoalRunner(max_iterations=10)

    result = runner.run("Test goal", state)
    assert result.status == "completed"
    assert result.iterations == 2



def test_token_budget_exhausted() -> None:
    """Loop should stop when token budget is exceeded."""
    state = _make_app_state([evaluate_goal_response(False, "Working...")])
    # Set a very low token budget — the system prompt alone is >200 tokens
    runner = GoalRunner(max_iterations=50, max_tokens=100)

    result = runner.run("Test goal", state)
    assert result.status == "budget_exhausted"
    assert result.iterations < 5  # should bail quickly


def test_goal_token_budget_uses_context_delta(monkeypatch: pytest.MonkeyPatch) -> None:
    """Repeated unchanged context should not be charged as new tokens each iteration."""
    state = _make_app_state([
        evaluate_goal_response(False, "Still working..."),
        evaluate_goal_response(True, "Done."),
    ])
    monkeypatch.setattr("harness_poc.core.runtime.goal_runner.count_tokens", lambda _messages: 100)
    runner = GoalRunner(max_iterations=10, max_tokens=150)

    result = runner.run("Test goal", state)

    assert result.status == "completed"
    assert result.iterations == 2
    assert result.total_tokens < 150


def test_stuck_detection_blocks_repeated_failed_action() -> None:
    """Semantic stuck detection blocks actions that previously failed (not successful ones)."""
    # First attempt: nonexistent_skill fails
    state = _make_app_state([
        tool_call_response("nonexistent_skill", {}),
        tool_call_response("nonexistent_skill", {}),
        tool_call_response("nonexistent_skill", {}),
        tool_call_response("nonexistent_skill", {}),
    ])
    runner = GoalRunner(max_iterations=10, stuck_threshold=3)

    result = runner.run("Test goal", state)
    assert result.status == "budget_exhausted"
    events = state.event_bus.get_recent_events(state.session_id)
    blocked = [e for e in events if isinstance(e, SkillCompleted) and e.status == "blocked"]
    assert len(blocked) >= 1

    # --- Verify semantic normalization: different whitespace/casing should
    # --- produce the same semantic key.
    from harness_poc.core.runtime import _semantic_key

    key1 = _semantic_key("semble_search", {"query": "BlackboardDatabase schema"})
    key2 = _semantic_key("semble_search", {"query": "BlackboardDatabase  schema"})
    key3 = _semantic_key("semble_search", {"query": "BLACKBOARDDATABASE SCHEMA"})
    assert key1 == key2 == key3

    # Different tool should produce different key
    key4 = _semantic_key("web_search", {"query": "BlackboardDatabase schema"})
    assert key1 != key4



def test_context_window_builds_from_events() -> None:
    """Verify that the context window is populated from bus events."""
    state = _make_app_state([
        tool_call_response("read_memory", {"memory_key": "test"}),
        evaluate_goal_response(True, "Done."),
    ])
    runner = GoalRunner(max_iterations=10, context_window=5)

    result = runner.run("Test", state)
    assert result.status == "completed"
    all_events = state.event_bus.get_recent_events(state.session_id)
    # AgentStarted + SkillCalled + SkillCompleted + GoalEvaluated = 4
    assert len(all_events) >= 4
    assert any(isinstance(e, AgentStarted) for e in all_events)


def test_goal_runner_streams_progress() -> None:
    state = _make_app_state([evaluate_goal_response(True, "Done.")])
    runner = GoalRunner(max_iterations=10)
    chunks: list[str] = []

    result = runner.run("Test goal", state, on_text=chunks.append)

    assert result.status == "completed"
    assert any("evaluate_goal" in chunk for chunk in chunks)
    assert any("Done." in chunk for chunk in chunks)
