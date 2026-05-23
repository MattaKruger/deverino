from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TypeVar

from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from harness_poc.core.events import BaseEvent, SkillCalled, SkillCompleted
from harness_poc.core.runtime import LLMResponse

if TYPE_CHECKING:
    from collections.abc import Callable

    from harness_poc.core.runtime import GoalRunResult, Message
    from harness_poc.core.skills import SkillResult

E = TypeVar("E", bound=BaseEvent)


class RecordingEventBus:
    """In-memory EventBus for tests — no persistence, no subscribers."""

    def __init__(self) -> None:
        self.events: list[BaseEvent] = []

    def publish(self, event: BaseEvent) -> None:
        self.events.append(event)

    def subscribe(self, event_type: type[E], handler: Callable[[E], None]) -> None:
        pass

    def get_recent_events(
        self,
        session_id: str,
        limit: int = 20,
        event_types: list[type[BaseEvent]] | None = None,
    ) -> list[BaseEvent]:
        filtered = [e for e in self.events if e.session_id == session_id]
        if event_types is not None:
            names = {t.__name__ for t in event_types}
            filtered = [e for e in filtered if type(e).__name__ in names]
        return filtered[-limit:]

    def get_all_events(
        self,
        session_id: str,
        event_types: list[type[BaseEvent]] | None = None,
    ) -> list[BaseEvent]:
        """Return all events for a session, optionally filtered by type."""
        filtered = [e for e in self.events if e.session_id == session_id]
        if event_types is not None:
            names = {t.__name__ for t in event_types}
            filtered = [e for e in filtered if type(e).__name__ in names]
        return filtered


# ---------------------------------------------------------------------------
# Mock LLM infrastructure
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


def _response_to_goal_action(response: LLMResponse) -> dict[str, Any]:
    """Convert an LLMResponse to a GoalAction-compatible dict."""
    if response.kind == "text":
        return {"tool_name": "_llm_text", "arguments": {}, "content": response.content}

    if response.tool_call is None:
        return {"tool_name": "_llm_text", "arguments": {}, "content": response.content}

    return {
        "tool_name": response.tool_call["name"],
        "arguments": response.tool_call.get("arguments", {}),
        "content": response.content,
    }


def _mock_goal_model(responses: list[LLMResponse]) -> FunctionModel:
    """Build a FunctionModel that consumes mock_responses in sequence."""
    respond = _mock_response_factory(responses)

    def _model_fn(_messages: list[Any], _info: AgentInfo) -> ModelResponse:
        response = respond([], None)
        action = _response_to_goal_action(response)
        return ModelResponse(parts=[TextPart(json.dumps(action))])

    return FunctionModel(_model_fn)


def tool_call_response(name: str, arguments: dict[str, Any]) -> LLMResponse:
    """Shorthand for a tool-call mock response."""
    return LLMResponse(
        kind="tool_call",
        content="",
        tool_call={"name": name, "arguments": arguments},
    )


def evaluate_goal_response(
    is_complete: bool,
    reasoning: str = "",
    final_answer: str = "",
) -> LLMResponse:
    """Shorthand for an evaluate_goal mock response."""
    args: dict[str, Any] = {"is_complete": is_complete, "reasoning": reasoning}
    if final_answer:
        args["final_answer"] = final_answer
    return LLMResponse(
        kind="tool_call",
        content="",
        tool_call={"name": "evaluate_goal", "arguments": args},
    )


def text_response(content: str) -> LLMResponse:
    """Shorthand for a plain-text mock response (no tool call)."""
    return LLMResponse(kind="text", content=content)


def skill_result(
    status: str = "success",
    content: str = "",
    **artifacts: Any,  # noqa: ANN401
) -> SkillResult:
    """Shorthand for a mock skill result — used with SessionHarness skill_overrides.

    Usage:
        from tests.helpers import skill_result

        harness = SessionHarness.build(
            [...],
            skill_overrides={
                "search_documents": skill_result(
                    status="success",
                    content="Found 3 documents.",
                    hit_count=3,
                ),
            },
        )
    """
    from harness_poc.core.skills import SkillResult  # noqa: PLC0415

    return SkillResult(status=status, content=content, artifacts=dict(artifacts))  # ty:ignore[invalid-argument-type]


# ---------------------------------------------------------------------------
# TraceAssertions
# ---------------------------------------------------------------------------


@dataclass
class TraceAssertions:
    """Assertion engine over a list of BaseEvent.

    Composed by SessionHarness; also usable standalone for lower-level
    event-trace assertions.
    """

    events: list[BaseEvent]

    # ------------------------------------------------------------------
    # Skill presence (query, not assert)
    # ------------------------------------------------------------------

    def skill_called(self, name: str) -> bool:
        """Return True if any SkillCalled event matches the skill name."""
        return any(
            isinstance(e, SkillCalled) and e.tool_name == name for e in self.events
        )

    def skill_completed(self, name: str, *, status: str | None = None) -> bool:
        """Return True if any SkillCompleted event matches name + optional status."""
        for e in self.events:
            if not isinstance(e, SkillCompleted):
                continue
            if name not in (e.tool_name, e.skill_name):
                continue
            if status is not None and e.status != status:
                continue
            return True
        return False

    @property
    def skill_calls(self) -> list[SkillCalled]:
        """All SkillCalled events in chronological order."""
        return [e for e in self.events if isinstance(e, SkillCalled)]

    @property
    def skill_results(self) -> list[SkillCompleted]:
        """All SkillCompleted events in chronological order."""
        return [e for e in self.events if isinstance(e, SkillCompleted)]

    # ------------------------------------------------------------------
    # Order assertions
    # ------------------------------------------------------------------

    def assert_skill_called(self, name: str) -> None:
        """Raise AssertionError if skill was never called."""
        if not self.skill_called(name):
            called = [e.tool_name for e in self.skill_calls]
            msg = (
                f"Expected skill '{name}' to be called, "
                f"but only saw: {called or '(no skills called)'}"
            )
            raise AssertionError(msg)

    def assert_skill_not_called(self, name: str) -> None:
        """Raise AssertionError if skill was called."""
        if self.skill_called(name):
            msg = f"Expected skill '{name}' NOT to be called, but it was."
            raise AssertionError(msg)

    def assert_skill_order(self, *names: str) -> None:
        """Assert skill calls appear in this relative order (not necessarily adjacent).

        Uses a positional scan: for each expected name, finds the next
        occurrence after the previous match.
        """
        called_names = [e.tool_name for e in self.skill_calls]
        cursor = 0  # position in called_names
        missing: list[str] = []

        for expected in names:
            try:
                cursor = called_names.index(expected, cursor) + 1
            except ValueError:
                missing.append(expected)

        if missing:
            msg = (
                f"Expected skill order {list(names)}, "
                f"but got: {called_names or '(no skills called)'}. "
                f"Missing in order: {missing}"
            )
            raise AssertionError(msg)

    def assert_skill_completed(self, name: str, *, status: str = "success") -> None:
        """Assert skill completed with given status."""
        if not self.skill_completed(name, status=status):
            completed = [
                f"{e.tool_name}({e.status})"
                for e in self.skill_results
                if name in (e.tool_name, e.skill_name)
            ]
            msg = (
                f"Expected skill '{name}' to complete with status='{status}', "
                f"but completions were: {completed or '(none)'}"
            )
            raise AssertionError(msg)

    # ------------------------------------------------------------------
    # Event introspection
    # ------------------------------------------------------------------

    def events_of_type(self, event_type: type[E]) -> list[E]:
        """All events matching the given type."""
        return [e for e in self.events if isinstance(e, event_type)]

    @property
    def all_events(self) -> list[BaseEvent]:
        """All recorded events."""
        return list(self.events)

    # ------------------------------------------------------------------
    # Goal result assertions
    # ------------------------------------------------------------------

    @staticmethod
    def assert_completed(result: GoalRunResult) -> None:
        """Assert result.status == 'completed'."""
        if result.status != "completed":
            msg = (
                f"Expected goal to complete (status='completed'), "
                f"but got status='{result.status}'. Content: {result.content[:200]}"
            )
            raise AssertionError(msg)

    @staticmethod
    def assert_budget_exhausted(result: GoalRunResult) -> None:
        """Assert result.status == 'budget_exhausted'."""
        if result.status != "budget_exhausted":
            msg = (
                f"Expected budget exhaustion (status='budget_exhausted'), "
                f"but got status='{result.status}'."
            )
            raise AssertionError(msg)

    @staticmethod
    def assert_final_answer_contains(result: GoalRunResult, *fragments: str) -> None:
        """Assert result.content contains all fragments (case-insensitive)."""
        content_lower = result.content.lower()
        missing = [f for f in fragments if f.lower() not in content_lower]
        if missing:
            msg = (
                f"Expected final answer to contain fragments: {list(fragments)}. "
                f"Missing: {missing}. Answer: {result.content[:300]}"
            )
            raise AssertionError(msg)
