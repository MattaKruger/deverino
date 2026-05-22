"""Fixtures and skip logic for benchmark tests (real LLM)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import pytest

from harness_poc.app_factory import AppState, build_app_state
from harness_poc.core.config import LLMConfig
from harness_poc.core.goal_runner import GoalRunner, GoalRunResult
from harness_poc.core.pydantic_runtime import build_model
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
    """Thin wrapper so benchmark tests call run() like SessionHarness."""

    state: AppState

    def run(self, goal: str) -> GoalRunResult:
        runner = GoalRunner(max_iterations=30, max_tokens=20_000)
        return runner.run(goal, self.state)


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
