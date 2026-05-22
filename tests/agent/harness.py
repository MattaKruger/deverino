"""SessionHarness — controlled test surface for mock-LLM GoalRunner sessions."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from sqlalchemy import create_engine as sa_create_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel

from harness_poc.app_factory import (
    AppState,
    Identity,
    LongLived,
    Runtime,
    StreamingContext,
)
from harness_poc.core.config import HarnessConfig
from harness_poc.core.database import BlackboardDatabase
from harness_poc.core.goal_runner import GoalRunner, GoalRunResult
from harness_poc.core.llm_client import LLMResponse
from harness_poc.core.skill_runner import SkillRunner
from tests.helpers import RecordingEventBus, TraceAssertions

if TYPE_CHECKING:
    from collections.abc import Callable

    from harness_poc.core.events import BaseEvent, SkillCalled, SkillCompleted
    from harness_poc.core.llm_client import Message


# ---------------------------------------------------------------------------
# Mock LLM helpers
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


# ---------------------------------------------------------------------------
# Response factory shorthands (re-exported by conftest for test ergonomics)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# SessionHarness
# ---------------------------------------------------------------------------


@dataclass
class SessionHarness:
    """Controlled test surface for mock-LLM GoalRunner sessions.

    Usage:
        harness = SessionHarness.build([
            tool_call_response("read_memory", {"memory_key": "test"}),
            evaluate_goal_response(True, "Done.", "Final answer."),
        ])
        harness.run("summarise the project state")
        harness.assert_skill_called("read_memory")  # evaluate_goal is intercepted, not called
        harness.assert_completed()
    """

    state: AppState
    runner: GoalRunner
    result: GoalRunResult | None = None

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def build(
        cls,
        mock_responses: list[LLMResponse],
        *,
        max_iterations: int = 10,
        stuck_threshold: int = 3,
        context_window: int = 20,
    ) -> SessionHarness:
        """Construct a harness with a FunctionModel-backed GoalRunner.

        Args:
            mock_responses: Sequence of LLMResponse objects the mock
                model will return, in order. The last response repeats
                when exhausted.
            max_iterations: GoalRunner iteration limit.
            stuck_threshold: Semantic stuck detection sensitivity.
            context_window: Number of recent events in LLM context.

        """
        # 1. In-memory SQLite engine + BlackboardDatabase
        # StaticPool ensures all connections share the same :memory: database.
        engine = sa_create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        # Import database module to ensure SQLModel table classes are registered
        import harness_poc.core.database  # noqa: F401, PLC0415
        SQLModel.metadata.create_all(engine)
        database = BlackboardDatabase(engine)

        # 2. RecordingEventBus (in-memory, no persistence)
        event_bus = RecordingEventBus()

        # 3. Load real config for paths (skill discovery needs real paths on disk)
        config = HarnessConfig.load()

        # 4. SkillRunner — discovers skills from project + system skill dirs
        skill_runner = SkillRunner(database=database, config=config)
        tools = skill_runner.discover_skills()

        # 5. Mock LLM model
        mock_model = _mock_goal_model(mock_responses)

        # 6. GoalRunner
        runner = GoalRunner(
            max_iterations=max_iterations,
            stuck_threshold=stuck_threshold,
            context_window=context_window,
            decision_model=mock_model,
        )

        # 7. Assemble AppState manually to use RecordingEventBus
        session_id = database.start_session("Test session")
        identity = Identity(
            session_id=session_id,
            database=database,
            event_bus=event_bus,  # type: ignore[arg-type] — RecordingEventBus is compatible at runtime
            event_store=None,  # type: ignore[arg-type] — not used by RecordingEventBus
            config_project_root=config.project_root,
            config_project_id=config.project_id,
        )
        runtime = Runtime(
            config=config,
            skill_runner=skill_runner,
            tool_runner=None,  # type: ignore[arg-type] — not used by GoalRunner
            skill_scaffolder=None,  # type: ignore[arg-type]
            workflow_runner=None,  # type: ignore[arg-type]
            pipeline_runner=None,  # type: ignore[arg-type]
            pydantic_runtime=None,  # type: ignore[arg-type]
            tools=tools,
            skill_catalog="",
        )
        long_lived = LongLived(
            materializer=None,  # type: ignore[arg-type]
            supervisor=None,  # type: ignore[arg-type]
        )
        state = AppState(
            identity=identity,
            runtime=runtime,
            long_lived=long_lived,
            pydantic_messages=[],
            goal_decision_model=mock_model,
            messages=[],
            streaming=StreamingContext(),
        )

        return cls(state=state, runner=runner)

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def run(self, goal: str) -> GoalRunResult:
        """Execute the goal loop and store the result."""
        self.result = self.runner.run(goal, self.state)
        return self.result

    # ------------------------------------------------------------------
    # Skill assertions (delegated to TraceAssertions)
    # ------------------------------------------------------------------

    @property
    def _trace(self) -> TraceAssertions:
        """TraceAssertions over the full event trace for this session."""
        return TraceAssertions(
            self.state.event_bus.get_all_events(self.state.session_id)  # type: ignore[union-attr]
        )

    def assert_skill_called(self, name: str) -> None:
        self._trace.assert_skill_called(name)

    def assert_skill_not_called(self, name: str) -> None:
        self._trace.assert_skill_not_called(name)

    def assert_skill_order(self, *names: str) -> None:
        self._trace.assert_skill_order(*names)

    def assert_skill_completed(self, name: str, *, status: str = "success") -> None:
        self._trace.assert_skill_completed(name, status=status)

    # ------------------------------------------------------------------
    # Outcome assertions
    # ------------------------------------------------------------------

    def assert_completed(self) -> None:
        TraceAssertions.assert_completed(self._require_result())

    def assert_budget_exhausted(self) -> None:
        TraceAssertions.assert_budget_exhausted(self._require_result())

    def assert_final_answer_contains(self, *fragments: str) -> None:
        TraceAssertions.assert_final_answer_contains(self._require_result(), *fragments)

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def skill_calls(self) -> list[SkillCalled]:
        return self._trace.skill_calls

    @property
    def skill_results(self) -> list[SkillCompleted]:
        return self._trace.skill_results

    @property
    def final_answer(self) -> str:
        return self._require_result().content

    @property
    def all_events(self) -> list[BaseEvent]:
        return self._trace.all_events

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _require_result(self) -> GoalRunResult:
        """Raise RuntimeError if run() hasn't been called yet."""
        if self.result is None:
            msg = "SessionHarness.run() must be called before assertions"
            raise RuntimeError(msg)
        return self.result
