"""Tests for GoalRunner, database event methods, evaluate_goal skill, and CLI/REPL integration."""

from __future__ import annotations

import tempfile
from collections.abc import Callable
from typing import Any

from typer.testing import CliRunner

from harness_poc.app_factory import AppState, build_app_state
from harness_poc.cli import app
from harness_poc.core.database import BlackboardDatabase
from harness_poc.core.goal_runner import GoalRunner, count_tokens
from harness_poc.core.llm_client import LLMClient, LLMResponse, Message

runner = CliRunner()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_response_factory(
    responses: list[LLMResponse],
) -> Callable[[list[Message], list[dict[str, Any]] | None], LLMResponse]:
    """Return a callable that returns responses in sequence, then repeats the last."""

    def _respond(
        _messages: list[Message], _tools: list[dict[str, Any]] | None
    ) -> LLMResponse:
        nonlocal responses
        if not responses:
            return LLMResponse(kind="text", content="No responses left.")
        response = responses.pop(0)
        # Keep the last response for any subsequent calls
        if not responses:
            responses.append(response)
        return response

    return _respond


def _evaluate_goal_response(is_complete: bool, reasoning: str = "") -> LLMResponse:
    return LLMResponse(
        kind="tool_call",
        content="",
        tool_call={
            "name": "evaluate_goal",
            "arguments": {"is_complete": is_complete, "reasoning": reasoning},
        },
    )


def _tool_call_response(name: str, arguments: dict[str, Any]) -> LLMResponse:
    return LLMResponse(
        kind="tool_call",
        content="",
        tool_call={"name": name, "arguments": arguments},
    )


def _make_app_state(
    mock: (
        Callable[[list[Message], list[dict[str, Any]] | None], LLMResponse] | None
    ) = None,
) -> AppState:
    """Build an AppState with an in-memory database and optional mock LLM."""
    state = build_app_state()
    if mock is not None:
        state.llm_client = LLMClient(use_mock=True, mock_response=mock)
    return state


# ---------------------------------------------------------------------------
# Database event recording + retrieval
# ---------------------------------------------------------------------------


def _temp_db() -> BlackboardDatabase:
    """Create a BlackboardDatabase backed by a temporary file.

    Uses a file path (not :memory:) so that multiple connections
    within the database class share the same database.
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        db_path = tf.name
    db = BlackboardDatabase(db_path)
    db.create_tables()
    return db


def test_record_and_retrieve_events() -> None:
    db = _temp_db()
    sid = db.start_session("test")

    db.record_llm_action(sid, "read_memory", {"memory_key": "x"})
    db.record_tool_observation(sid, "read_memory", "success", "result content")

    events = db.get_recent_events(sid, limit=10)
    assert len(events) == 2
    assert events[0].event_type == "llm_action"
    assert events[1].event_type == "tool_observation"


def test_get_recent_events_respects_limit() -> None:
    db = _temp_db()
    sid = db.start_session("test")

    for i in range(5):
        db.record_llm_action(sid, "skill", {"n": i})

    events = db.get_recent_events(sid, limit=3)
    assert len(events) == 3
    # Should be most recent 3 in chronological order
    assert events[0].payload["arguments"]["n"] == 2
    assert events[2].payload["arguments"]["n"] == 4


def test_get_recent_events_returns_chronological() -> None:
    db = _temp_db()
    sid = db.start_session("test")

    db.record_llm_action(sid, "first", {})
    db.record_tool_observation(sid, "first", "success", "ok")
    db.record_llm_action(sid, "second", {})

    events = db.get_recent_events(sid, limit=10)
    assert len(events) == 3
    # Chronological order: first llm_action, first observation, second llm_action
    assert events[0].event_type == "llm_action"
    assert events[0].payload["tool_name"] == "first"
    assert events[2].payload["tool_name"] == "second"


def test_get_recent_events_filters_non_goal_events() -> None:
    """Only llm_action and tool_observation should be returned."""
    db = _temp_db()
    sid = db.start_session("test")

    db.record_llm_action(sid, "skill", {})
    # Insert a non-goal event (like append_notes) via the public append method
    db.append_session_state(sid, "notes", "some note")  # type: ignore[arg-type]
    db.record_tool_observation(sid, "skill", "success", "ok")

    events = db.get_recent_events(sid, limit=10)
    assert len(events) == 2
    assert all(
        e.event_type in ("llm_action", "tool_observation") for e in events
    )


# ---------------------------------------------------------------------------
# evaluate_goal skill
# ---------------------------------------------------------------------------


def test_evaluate_goal_skill_registered() -> None:
    state = _make_app_state()
    tools = state.skill_runner.discover_skills()
    names = {
        tool["function"]["name"]
        for tool in tools
        if isinstance(tool.get("function"), dict)
    }
    assert "evaluate_goal" in names


def test_evaluate_goal_stub_execute() -> None:
    state = _make_app_state()
    result = state.skill_runner.execute_skill(
        tool_name="evaluate_goal",
        arguments={"is_complete": True, "reasoning": "Done."},
        session_id=state.session_id,
    )
    assert result.status == "success"
    assert "complete=True" in result.content


# ---------------------------------------------------------------------------
# GoalRunner loop behavior (mock LLM)
# ---------------------------------------------------------------------------


def test_completes_on_evaluate_goal_true() -> None:
    mock = _mock_response_factory(
        [_evaluate_goal_response(True, "Task finished successfully.")]
    )
    state = _make_app_state(mock)
    runner = GoalRunner(max_iterations=10)

    result = runner.run("Test goal", state)
    assert result.status == "completed"
    assert result.iterations == 1
    assert "Task finished" in result.content


def test_continues_on_evaluate_goal_false() -> None:
    mock = _mock_response_factory(
        [
            _evaluate_goal_response(False, "Need more work."),
            _evaluate_goal_response(True, "Now done."),
        ]
    )
    state = _make_app_state(mock)
    runner = GoalRunner(max_iterations=10)

    result = runner.run("Test goal", state)
    assert result.status == "completed"
    assert result.iterations == 2


def test_text_response_without_tool_call() -> None:
    """Text responses should be recorded and loop continues."""
    mock = _mock_response_factory(
        [
            LLMResponse(kind="text", content="Let me think about this..."),
            _evaluate_goal_response(True, "I thought about it."),
        ]
    )
    state = _make_app_state(mock)
    runner = GoalRunner(max_iterations=10)

    result = runner.run("Test goal", state)
    assert result.status == "completed"
    assert result.iterations == 2
    # Verify text was recorded as observation
    events = state.database.get_recent_events(state.session_id, limit=10)
    text_observations = [
        e for e in events if e.payload.get("tool_name") == "_llm_text"
    ]
    assert len(text_observations) == 1


def test_iteration_budget_exhausted() -> None:
    """Loop should stop when max_iterations is reached."""
    mock = _mock_response_factory(
        [_evaluate_goal_response(False, "Still working...")]
    )
    state = _make_app_state(mock)
    runner = GoalRunner(max_iterations=3)

    result = runner.run("Test goal", state)
    assert result.status == "budget_exhausted"
    assert result.iterations == 3


def test_token_budget_exhausted() -> None:
    """Loop should stop when token budget is exceeded."""
    mock = _mock_response_factory(
        [_evaluate_goal_response(False, "Working...")]
    )
    state = _make_app_state(mock)
    # Set a very low token budget — the system prompt alone is >200 tokens
    runner = GoalRunner(max_iterations=50, max_tokens=100)

    result = runner.run("Test goal", state)
    assert result.status == "budget_exhausted"
    assert result.iterations < 5  # should bail quickly


def test_stuck_detection_blocks_fourth_identical_action() -> None:
    """Identical (tool, args) 4 times in a row should trigger stuck detection."""
    mock = _mock_response_factory(
        [_tool_call_response("read_memory", {"memory_key": "x"})]
    )
    state = _make_app_state(mock)
    runner = GoalRunner(max_iterations=10, stuck_threshold=3)

    result = runner.run("Test goal", state)
    # Should have hit stuck detection and eventually exhausted budget
    assert result.status == "budget_exhausted"
    # Verify stuck detection blocked at least once
    events = state.database.get_recent_events(state.session_id, limit=30)
    blocked = [
        e
        for e in events
        if e.event_type == "tool_observation"
        and e.payload.get("status") == "blocked"
    ]
    assert len(blocked) >= 1


def test_skill_execution_error_handled() -> None:
    """Skill errors should be recorded and loop continues."""
    # Use a non-existent skill name — this raises ValueError in _find_skill_file.
    mock = _mock_response_factory(
        [
            _tool_call_response("nonexistent_skill", {}),
            _evaluate_goal_response(True, "Handled error."),
        ]
    )
    state = _make_app_state(mock)
    runner = GoalRunner(max_iterations=10)

    result = runner.run("Test goal", state)
    # Should complete after the error handling
    assert result.status == "completed"
    events = state.database.get_recent_events(state.session_id, limit=20)
    errors = [
        e
        for e in events
        if e.event_type == "tool_observation"
        and e.payload.get("status") == "error"
    ]
    assert len(errors) >= 1


def test_context_window_builds_from_events() -> None:
    """Verify that the message builder uses recent events correctly."""
    # We test this indirectly: run a few iterations, then check that
    # events are being recorded and the loop reads them back.
    mock = _mock_response_factory(
        [
            _tool_call_response("read_memory", {"memory_key": "test"}),
            _evaluate_goal_response(True, "Done."),
        ]
    )
    state = _make_app_state(mock)
    runner = GoalRunner(max_iterations=10, context_window=5)

    result = runner.run("Test", state)
    assert result.status == "completed"
    events = state.database.get_recent_events(state.session_id, limit=20)
    assert len(events) >= 4


# ---------------------------------------------------------------------------
# Token counting
# ---------------------------------------------------------------------------


def test_count_tokens_basic() -> None:
    tokens = count_tokens([{"role": "user", "content": "hello"}])
    assert tokens > 0
    assert tokens < 20  # "hello" is just a few tokens


def test_count_tokens_scales_with_length() -> None:
    short = count_tokens([{"role": "user", "content": "hi"}])
    long = count_tokens([{"role": "user", "content": "hi " * 500}])
    assert long > short * 10


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_goal_cli_command_help() -> None:
    result = runner.invoke(app, ["goal", "--help"])
    assert result.exit_code == 0
    assert "autonomous ReAct" in result.output.lower() or "goal" in result.output


def test_goal_cli_executes_with_mock() -> None:
    """CLI should run the goal command without crashing (mock LLM)."""
    result = runner.invoke(
        app, ["goal", "test objective", "--max-iterations", "1"]
    )
    assert result.exit_code == 0
    assert "Status:" in result.output
