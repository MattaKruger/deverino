"""Benchmark tests: real LLM sessions validated against rubrics.

Run with:
    BENCHMARK_MODEL=claude-haiku-4-5-20251001 pytest tests/bench/ --run-benchmarks
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from tests.bench.conftest import _LiveSession
    from tests.bench.rubric_loader import Rubric


@pytest.mark.benchmark
def test_summarise_blackboard_database(
    live_session: _LiveSession,
    rubric: Rubric,
) -> None:
    """Validate agent quality: summarise the BlackboardDatabase.

    Hard gates (free) run first — fail-fast on structural issues.
    LLM judge (token cost) only fires if hard gates pass.
    """
    result = live_session.run(rubric.goal)
    rubric.assert_hard_gates(result, events=live_session.events)
    score = rubric.judge(result.content, config=live_session.state.config.llm)
    assert score is not None, "Rubric must define LLM Judge section for benchmarks"
    assert score >= rubric.judge_threshold, (  # ty:ignore[unsupported-operator]
        f"Judge score {score} below threshold {rubric.judge_threshold}"
    )
