"""Tests for GoalRunner, database event methods, evaluate_goal skill, and CLI/REPL integration."""

# ruff: noqa: FBT001, FBT003, PLR2004

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from typer.testing import CliRunner

from harness_poc.app_factory import AppState, build_app_state
from harness_poc.cli import app
from harness_poc.core.events import AgentStarted, LLMTextEmitted, SkillCompleted
from harness_poc.core.goal_runner import GoalRunner, count_tokens
from harness_poc.core.llm_client import LLMResponse, Message

if TYPE_CHECKING:
    from collections.abc import Callable

    import pytest

runner = CliRunner()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_response_factory(
    responses: list[LLMResponse],
) -> Callable[[list[Message], list[dict[str, Any]] | None], LLMResponse]:
    """Return a callable that returns responses in sequence, then repeats the last."""

    def _respond(_messages: list[Message], _tools: list[dict[str, Any]] | None) -> LLMResponse:
        nonlocal responses
        if not responses:
            return LLMResponse(kind="text", content="No responses left.")
        response = responses.pop(0)
        # Keep the last response for any subsequent calls
        if not responses:
            responses.append(response)
        return response

    return _respond


def _evaluate_goal_response(
    is_complete: bool,
    reasoning: str = "",
    final_answer: str = "",
) -> LLMResponse:
    arguments: dict[str, Any] = {
        "is_complete": is_complete,
        "reasoning": reasoning,
    }
    if final_answer:
        arguments["final_answer"] = final_answer
    return LLMResponse(
        kind="tool_call",
        content="",
        tool_call={
            "name": "evaluate_goal",
            "arguments": arguments,
        },
    )


def _tool_call_response(name: str, arguments: dict[str, Any]) -> LLMResponse:
    return LLMResponse(
        kind="tool_call",
        content="",
        tool_call={"name": name, "arguments": arguments},
    )


def _make_app_state(
    mock: (Callable[[list[Message], list[dict[str, Any]] | None], LLMResponse] | None) = None,
) -> AppState:
    """Build an AppState with an in-memory database and optional mock LLM."""
    state = build_app_state()
    if mock is not None:
        state.goal_decision_model = _mock_goal_model(mock)
    return state


def _mock_goal_model(
    mock: Callable[[list[Message], list[dict[str, Any]] | None], LLMResponse],
) -> FunctionModel:
    def _respond(
        _messages: list[Any],
        _info: AgentInfo,
    ) -> ModelResponse:
        response = mock([], None)
        action = _response_to_goal_action(response)

        return ModelResponse(parts=[TextPart(json.dumps(action))])

    return FunctionModel(_respond)


def _response_to_goal_action(response: LLMResponse) -> dict[str, Any]:
    if response.kind == "text":
        return {
            "tool_name": "_llm_text",
            "arguments": {},
            "content": response.content,
        }

    if response.tool_call is None:
        return {
            "tool_name": "_llm_text",
            "arguments": {},
            "content": response.content,
        }

    return {
        "tool_name": response.tool_call["name"],
        "arguments": response.tool_call["arguments"],
        "content": response.content,
    }


# ---------------------------------------------------------------------------
# evaluate_goal skill
# ---------------------------------------------------------------------------


def test_evaluate_goal_skill_registered() -> None:
    state = _make_app_state()
    tools = state.skill_runner.discover_skills()
    names = {tool["function"]["name"] for tool in tools if isinstance(tool.get("function"), dict)}
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


def test_completes_on_evaluate_goal_true() -> None:
    mock = _mock_response_factory([_evaluate_goal_response(True, "Task finished successfully.")])
    state = _make_app_state(mock)
    runner = GoalRunner(max_iterations=10)

    result = runner.run("Test goal", state)
    assert result.status == "completed"
    assert result.iterations == 1
    assert "Task finished" in result.content


def test_completed_generation_goal_prefers_final_answer() -> None:
    mock = _mock_response_factory(
        [
            _evaluate_goal_response(
                True,
                "The commit message has been generated.",
                "feat: migrate goal runner to pydantic-ai",
            )
        ]
    )
    state = _make_app_state(mock)
    runner = GoalRunner(max_iterations=10)

    result = runner.run("generate a commit message", state)

    assert result.status == "completed"
    assert result.content == "feat: migrate goal runner to pydantic-ai"


def test_completed_generation_goal_uses_latest_artifact_for_meta_reasoning() -> None:
    mock = _mock_response_factory(
        [
            _tool_call_response("read_memory", {"memory_key": "commit_message"}),
            _evaluate_goal_response(
                True,
                "The delegate_task skill returned a comprehensive commit message.",
            ),
        ]
    )
    state = _make_app_state(mock)
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
    """Text responses should be recorded as LLMTextEmitted and loop continues."""
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
    events = state.event_bus.get_recent_events(state.session_id)
    text_events = [e for e in events if isinstance(e, LLMTextEmitted)]
    assert len(text_events) == 1


def test_iteration_budget_exhausted() -> None:
    """Loop should stop when max_iterations is reached."""
    mock = _mock_response_factory([_evaluate_goal_response(False, "Still working...")])
    state = _make_app_state(mock)
    runner = GoalRunner(max_iterations=3)

    result = runner.run("Test goal", state)
    assert result.status == "budget_exhausted"
    assert result.iterations == 3


def test_token_budget_exhausted() -> None:
    """Loop should stop when token budget is exceeded."""
    mock = _mock_response_factory([_evaluate_goal_response(False, "Working...")])
    state = _make_app_state(mock)
    # Set a very low token budget — the system prompt alone is >200 tokens
    runner = GoalRunner(max_iterations=50, max_tokens=100)

    result = runner.run("Test goal", state)
    assert result.status == "budget_exhausted"
    assert result.iterations < 5  # should bail quickly


def test_stuck_detection_blocks_fourth_identical_action() -> None:
    """Identical (tool, args) 4 times in a row should trigger stuck detection."""
    mock = _mock_response_factory([_tool_call_response("read_memory", {"memory_key": "x"})])
    state = _make_app_state(mock)
    runner = GoalRunner(max_iterations=10, stuck_threshold=3)

    result = runner.run("Test goal", state)
    assert result.status == "budget_exhausted"
    events = state.event_bus.get_recent_events(state.session_id)
    blocked = [e for e in events if isinstance(e, SkillCompleted) and e.status == "blocked"]
    assert len(blocked) >= 1


def test_skill_execution_error_handled() -> None:
    """Skill errors should be recorded as SkillCompleted(error) and loop continues."""
    mock = _mock_response_factory(
        [
            _tool_call_response("nonexistent_skill", {}),
            _evaluate_goal_response(True, "Handled error."),
        ]
    )
    state = _make_app_state(mock)
    runner = GoalRunner(max_iterations=10)

    result = runner.run("Test goal", state)
    assert result.status == "completed"
    events = state.event_bus.get_recent_events(state.session_id)
    errors = [e for e in events if isinstance(e, SkillCompleted) and e.status == "error"]
    assert len(errors) >= 1


def test_context_window_builds_from_events() -> None:
    """Verify that the context window is populated from bus events."""
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
    all_events = state.event_bus.get_recent_events(state.session_id)
    # AgentStarted + SkillCalled + SkillCompleted + GoalEvaluated = 4
    assert len(all_events) >= 4
    assert any(isinstance(e, AgentStarted) for e in all_events)


def test_goal_runner_streams_progress() -> None:
    mock = _mock_response_factory([_evaluate_goal_response(True, "Done.")])
    state = _make_app_state(mock)
    runner = GoalRunner(max_iterations=10)
    chunks: list[str] = []

    result = runner.run("Test goal", state, on_text=chunks.append)

    assert result.status == "completed"
    assert any("evaluate_goal" in chunk for chunk in chunks)
    assert any("Done." in chunk for chunk in chunks)


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


def test_goal_cli_executes_with_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    """CLI should run the goal command without crashing (mock LLM)."""
    mock = _mock_response_factory([_evaluate_goal_response(True, "CLI done.")])
    state = _make_app_state(mock)
    monkeypatch.setattr("harness_poc.cli.build_app_state", lambda: state)

    result = runner.invoke(app, ["goal", "test objective", "--max-iterations", "1"])
    assert result.exit_code == 0
    assert "Status:" in result.output
