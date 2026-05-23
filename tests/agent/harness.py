"""SessionHarness — controlled test surface for mock-LLM GoalRunner sessions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

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
from harness_poc.core.goal_runner import GoalRunner, GoalRunResult
from harness_poc.core.skill_runner import SkillRunner
from harness_poc.core.storage import BlackboardDatabase
from tests.helpers import (
    RecordingEventBus,
    TraceAssertions,
    _mock_goal_model,
)

if TYPE_CHECKING:
    from typing import Any

    from harness_poc.core.events import BaseEvent, SkillCalled, SkillCompleted
    from harness_poc.core.llm_client import LLMResponse
    from harness_poc.core.skill_context import SkillResult


# ---------------------------------------------------------------------------
# SkillOverrideProxy — intercepts specific skill names with mock results
# ---------------------------------------------------------------------------


class _SkillOverrideProxy:
    """Wraps SkillRunner, returning mock results for overridden skill names.

    All other attributes (discover_skills, cancel_call, etc.) delegate
    to the real runner. Only execute_skill is intercepted.
    """

    def __init__(self, real: SkillRunner, overrides: dict[str, SkillResult]) -> None:
        self._real = real
        self._overrides = overrides

    def execute_skill(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        session_id: str,
        **kwargs: Any,  # noqa: ANN401
    ) -> SkillResult:
        if tool_name in self._overrides:
            return self._overrides[tool_name]
        return self._real.execute_skill(
            tool_name=tool_name,
            arguments=arguments,
            session_id=session_id,
            **kwargs,
        )

    def __getattr__(self, name: str) -> Any:  # noqa: ANN401
        return getattr(self._real, name)


# ---------------------------------------------------------------------------
# SessionHarness
# ---------------------------------------------------------------------------


@dataclass
class SessionHarness:
    """Controlled test surface for mock-LLM GoalRunner sessions.

    Usage:
        from tests.helpers import tool_call_response, evaluate_goal_response

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
    _trace_cache: TraceAssertions | None = None

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def build(
        cls,
        mock_responses: list[LLMResponse],
        *,
        skill_overrides: dict[str, SkillResult] | None = None,
        max_iterations: int = 10,
        stuck_threshold: int = 3,
        context_window: int = 20,
    ) -> SessionHarness:
        """Construct a harness with a FunctionModel-backed GoalRunner.

        Args:
            mock_responses: Sequence of LLMResponse objects the mock
                model will return, in order. The last response repeats
                when exhausted.
            skill_overrides: Optional mapping of skill_name → SkillResult.
                When the mock LLM calls an overridden skill, the proxy
                returns the mock result instead of executing the real
                skill. Use for skills that need external services
                (search_documents, web_search, semble_search).
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
        import harness_poc.core.storage.database  # noqa: F401, PLC0415
        SQLModel.metadata.create_all(engine)
        database = BlackboardDatabase(engine)

        # 2. RecordingEventBus (in-memory, no persistence)
        event_bus = RecordingEventBus()

        # 3. Load real config for paths (skill discovery needs real paths on disk)
        config = HarnessConfig.load()

        # 4. SkillRunner — discovers skills from project + system skill dirs
        real_runner = SkillRunner(database=database, config=config)
        skill_runner = (
            _SkillOverrideProxy(real_runner, skill_overrides)
            if skill_overrides
            else real_runner
        )
        tools = real_runner.discover_skills()

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
            event_bus=event_bus,  # type: ignore[arg-type] — RecordingEventBus is compatible at runtime  # ty:ignore[invalid-argument-type]
            event_store=None,  # type: ignore[arg-type] — not used by RecordingEventBus  # ty:ignore[invalid-argument-type]
            config_project_root=config.project_root,
            config_project_id=config.project_id,
        )
        runtime = Runtime(
            config=config,
            skill_runner=skill_runner,  # ty:ignore[invalid-argument-type]
            tool_runner=None,  # type: ignore[arg-type] — not used by GoalRunner  # ty:ignore[invalid-argument-type]
            skill_scaffolder=None,  # type: ignore[arg-type]  # ty:ignore[invalid-argument-type]
            workflow_runner=None,  # type: ignore[arg-type]  # ty:ignore[invalid-argument-type]
            pipeline_runner=None,  # type: ignore[arg-type]  # ty:ignore[invalid-argument-type]
            pydantic_runtime=None,  # type: ignore[arg-type]  # ty:ignore[invalid-argument-type]
            tools=tools,
            skill_catalog="",
        )
        long_lived = LongLived(
            materializer=None,  # type: ignore[arg-type]  # ty:ignore[invalid-argument-type]
            supervisor=None,  # type: ignore[arg-type]  # ty:ignore[invalid-argument-type]
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
        """TraceAssertions over the full event trace for this session.

        Built once on first access and cached — events don't change after run().
        """
        if self._trace_cache is None:
            self._trace_cache = TraceAssertions(
                self.state.event_bus.get_all_events(self.state.session_id)  # type: ignore[union-attr]  # ty:ignore[unresolved-attribute]
            )
        return self._trace_cache

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
