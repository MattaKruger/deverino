"""Fixtures and skip logic for benchmark tests (real LLM)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from harness_poc.app_factory import AppState, build_app_state
from harness_poc.core.config import LLMConfig
from harness_poc.core.events import (
    BaseEvent,
    GoalEvaluated,
    LLMTextEmitted,
    SkillCalled,
    SkillCompleted,
)
from harness_poc.core.runtime import GoalRunner, GoalRunResult, build_model
from tests.bench.rubric_loader import Rubric

# Default models — overridable via env vars for cross-model comparison.
BENCHMARK_MODEL = os.getenv("BENCHMARK_MODEL", "claude-haiku-4-5-20251001")
BENCHMARK_JUDGE_MODEL = os.getenv("BENCHMARK_JUDGE_MODEL", BENCHMARK_MODEL)
BENCHMARK_DATABASE_URL = os.getenv("TEST_DATABASE_URL", "")

RUBRICS_DIR = Path(__file__).parent / "rubrics"


# ---------------------------------------------------------------------------
# LiveSession wrapper
# ---------------------------------------------------------------------------


@dataclass
class _LiveSession:
    """Thin wrapper so benchmark tests call run() like SessionHarness.

    After run(), captures the event trace from the EventBus so
    rubrics can validate skill_sequence via TraceAssertions.
    """

    state: AppState
    _events: list[BaseEvent] = field(default_factory=list, init=False)

    def run(self, goal: str) -> GoalRunResult:
        runner = GoalRunner(max_iterations=30, max_tokens=20_000)
        result = runner.run(goal, self.state)

        # Capture event trace for process validation (skill_sequence, etc.).
        # EventBus.get_recent_events queries the real EventStore (Postgres)
        # and returns BaseEvent objects compatible with TraceAssertions.
        self._events = self.state.event_bus.get_recent_events(
            self.state.session_id,
            limit=10_000,
            event_types=[SkillCalled, SkillCompleted, GoalEvaluated, LLMTextEmitted],
        )
        return result

    @property
    def events(self) -> list[BaseEvent]:
        """Event trace captured during the last run().

        Returns BaseEvent objects suitable for TraceAssertions.
        Empty list if run() hasn't been called yet.
        """
        return self._events

    def assert_skill_order(self, *names: str) -> None:
        """Validate the order of skill calls from the event trace."""
        from tests.helpers import TraceAssertions  # noqa: PLC0415

        TraceAssertions(self._events).assert_skill_order(*names)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def live_session() -> _LiveSession:
    """GoalRunner wired to a real LLM via BENCHMARK_MODEL env var.

    Uses the configured test database (TEST_DATABASE_URL) or falls back
    to the harness.yaml database_url.
    """
    kwargs: dict[str, str] = {}
    if BENCHMARK_DATABASE_URL:
        kwargs["database_url"] = BENCHMARK_DATABASE_URL

    state = build_app_state(**kwargs)  # type: ignore[arg-type]

    # Override the decision model with BENCHMARK_MODEL
    state.goal_decision_model = build_model(
        LLMConfig(
            provider=state.config.llm.provider,
            model=BENCHMARK_MODEL,
            base_url=state.config.llm.base_url,
        )
    )

    return _LiveSession(state)


@pytest.fixture
def rubric(request: pytest.FixtureRequest) -> Rubric:
    """Load a rubric by convention from the test function name.

    test_summarise_blackboard_database → summarise-blackboard-database.md
    """
    test_name = request.function.__name__
    # Strip "test_" prefix and convert underscores to hyphens
    slug = test_name.removeprefix("test_").replace("_", "-")
    rubric_path = RUBRICS_DIR / f"{slug}.md"

    if not rubric_path.exists():
        msg = (
            f"No rubric found for test '{test_name}'. "
            f"Expected: {rubric_path}"
        )
        raise FileNotFoundError(msg)

    return Rubric.from_markdown(rubric_path)


# ---------------------------------------------------------------------------
# Skip logic: benchmarks are opt-in via --run-benchmarks
# ---------------------------------------------------------------------------


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-benchmarks",
        action="store_true",
        default=False,
        help="Run benchmark tests (real LLM calls — skipped by default)",
    )


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    if not config.getoption("--run-benchmarks", default=False):
        skip_bench = pytest.mark.skip(reason="--run-benchmarks not set")
        for item in items:
            if "bench" in str(item.fspath):
                item.add_marker(skip_bench)
