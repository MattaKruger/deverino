"""Tests for evaluation infrastructure (Phase 2 hardening).

Verifies that EvalRunner, JudgeEvaluator, and EvalTask load and score
correctly. These tests run offline (no LLM required) using the heuristic
judge and placeholder runner.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from harness_poc.core.eval.judge import JudgeEvaluator
from harness_poc.core.eval.runner import EvalReport, EvalRunner
from harness_poc.core.eval.task import EvalTask, EvalTaskEval

# ---------------------------------------------------------------------------
# EvalTask YAML loading
# ---------------------------------------------------------------------------


def test_load_all_tasks_finds_expected_count():
    """At least 10 task YAML files should load without errors."""
    tasks_dir = Path("evals/tasks")
    if not tasks_dir.exists():
        pytest.skip("evals/tasks/ directory not found")
    tasks = EvalTask.load_all(tasks_dir)
    assert len(tasks) >= 10, f"Expected at least 10 tasks, got {len(tasks)}"


def test_load_all_tasks_have_required_fields():
    """Every task must have name, category, and input fields."""
    tasks_dir = Path("evals/tasks")
    if not tasks_dir.exists():
        pytest.skip("evals/tasks/ directory not found")
    tasks = EvalTask.load_all(tasks_dir)
    for task in tasks:
        assert task.name, f"Task {task} missing name"
        assert task.category, f"Task {task.name} missing category"
        assert task.evaluation.type in (
            "trait_check",
            "binary",
            "llm_judge",
        ), f"Task {task.name} has unknown eval type: {task.evaluation.type}"


def test_category_distribution():
    """Verify we have tasks across all 5 required categories."""
    tasks_dir = Path("evals/tasks")
    if not tasks_dir.exists():
        pytest.skip("evals/tasks/ directory not found")
    tasks = EvalTask.load_all(tasks_dir)
    categories = {t.category for t in tasks}
    required = {
        "code_understanding",
        "file_operations",
        "multi_step",
        "skill_delegation",
        "error_recovery",
    }
    missing = required - categories
    assert not missing, f"Missing categories: {missing}"


# ---------------------------------------------------------------------------
# EvalRunner — offline mode
# ---------------------------------------------------------------------------


def test_runner_run_all_produces_report():
    """run_all() returns an EvalReport with results for every task."""
    tasks_dir = Path("evals/tasks")
    if not tasks_dir.exists():
        pytest.skip("evals/tasks/ directory not found")
    runner = EvalRunner(tasks_dir=tasks_dir, results_dir=Path("evals/results"))
    report = runner.run_all()

    assert isinstance(report, EvalReport)
    assert report.tasks_total >= 10
    assert len(report.results) >= 10
    assert 0 <= report.average_score <= 5.0
    assert report.tasks_passed + report.tasks_failed == report.tasks_total


def test_runner_filter_by_category():
    """Category filter returns only matching tasks."""
    tasks_dir = Path("evals/tasks")
    if not tasks_dir.exists():
        pytest.skip("evals/tasks/ directory not found")
    runner = EvalRunner(tasks_dir=tasks_dir, results_dir=Path("evals/results"))
    report = runner.run_all(category="code_understanding")
    assert report.tasks_total >= 3
    for result in report.results:
        assert result["category"] == "code_understanding"


def test_runner_run_one_by_name():
    """run_one() returns a single task result."""
    tasks_dir = Path("evals/tasks")
    if not tasks_dir.exists():
        pytest.skip("evals/tasks/ directory not found")
    runner = EvalRunner(tasks_dir=tasks_dir, results_dir=Path("evals/results"))
    result = runner.run_one("code_explain_guard_pipeline")
    assert result["task"] == "code_explain_guard_pipeline"
    assert "score" in result
    assert "passed" in result
    assert "explanation" in result


def test_runner_write_report_creates_file():
    """Report JSON is written to the results directory."""
    tasks_dir = Path("evals/tasks")
    results_dir = Path("evals/results")
    if not tasks_dir.exists():
        pytest.skip("evals/tasks/ directory not found")
    runner = EvalRunner(tasks_dir=tasks_dir, results_dir=results_dir)
    report = runner.run_all()
    # Should have written a JSON file
    json_files = list(results_dir.glob("*.json"))
    assert len(json_files) >= 1, f"No report JSON found in {results_dir}"


# ---------------------------------------------------------------------------
# JudgeEvaluator
# ---------------------------------------------------------------------------


def test_judge_trait_check_all_matched():
    """When all traits are present, score should be 5.0 and passed=True."""
    judge = JudgeEvaluator()
    task = EvalTask(
        name="test_trait",
        category="test",
        evaluation=EvalTaskEval(
            type="trait_check",
            expected_traits=["alpha", "beta", "gamma"],
            min_traits=2,
        ),
    )
    result = judge.evaluate(task, "This output contains alpha, beta, and gamma clearly.")
    assert result.score == 5.0
    assert result.passed is True
    assert result.trait_results == {"alpha": True, "beta": True, "gamma": True}


def test_judge_trait_check_partial():
    """Partial trait match gives proportional score."""
    judge = JudgeEvaluator()
    task = EvalTask(
        name="test_partial",
        category="test",
        evaluation=EvalTaskEval(
            type="trait_check",
            expected_traits=["alpha", "beta", "gamma"],
            min_traits=2,
        ),
    )
    # "beta" is still a substring of "but not beta", so keyword match finds it.
    # To test partial: use output that genuinely lacks one keyword.
    result = judge.evaluate(task, "This output mentions alpha and gamma clearly.")
    assert result.score == pytest.approx(3.33, abs=0.1)
    assert result.passed is True  # 2 >= min_traits
    assert result.trait_results["alpha"] is True
    assert result.trait_results["beta"] is False
    assert result.trait_results["gamma"] is True


def test_judge_trait_check_none_matched():
    """No traits matched means score 0.0 and failed."""
    judge = JudgeEvaluator()
    task = EvalTask(
        name="test_none",
        category="test",
        evaluation=EvalTaskEval(
            type="trait_check",
            expected_traits=["alpha", "beta"],
            min_traits=1,
        ),
    )
    result = judge.evaluate(task, "Completely unrelated output.")
    assert result.score == 0.0
    assert result.passed is False


def test_judge_binary_valid_output():
    """Non-error output should pass binary evaluation."""
    judge = JudgeEvaluator()
    task = EvalTask(
        name="test_binary",
        category="test",
        evaluation=EvalTaskEval(type="binary", min_score=1.0),
    )
    result = judge.evaluate(task, "This is a valid and complete response to the question.")
    assert result.passed is True
    assert result.score == 5.0


def test_judge_binary_error_output():
    """Output containing error markers should fail binary evaluation."""
    judge = JudgeEvaluator()
    task = EvalTask(
        name="test_binary_error",
        category="test",
        evaluation=EvalTaskEval(type="binary", min_score=1.0),
    )
    result = judge.evaluate(task, "Error: failed to process the request.")
    assert result.passed is False
    assert result.score == 1.0


def test_judge_binary_too_short():
    """Very short output should fail binary evaluation."""
    judge = JudgeEvaluator()
    task = EvalTask(
        name="test_binary_short",
        category="test",
        evaluation=EvalTaskEval(type="binary", min_score=1.0),
    )
    result = judge.evaluate(task, "ok")
    assert result.passed is False


def test_judge_heuristic_rubric_length():
    """Heuristic rubric scores higher for longer, structured output."""
    judge = JudgeEvaluator()
    task = EvalTask(
        name="test_heuristic",
        category="test",
        evaluation=EvalTaskEval(type="llm_judge", rubric="1-5 scale", min_score=3.0),
    )
    short = judge.evaluate(task, "short")
    assert short.score <= 2.0

    long_structured = judge.evaluate(task, "function example parameters returns " + ("x " * 200))
    assert long_structured.score >= 3.0


def test_judge_cache():
    """Repeated evaluations of the same input should hit the cache."""
    judge = JudgeEvaluator()
    task = EvalTask(
        name="test_cache",
        category="test",
        evaluation=EvalTaskEval(type="binary", min_score=1.0),
    )
    result1 = judge.evaluate(task, "cache test output here")
    result2 = judge.evaluate(task, "cache test output here")
    assert result1 == result2
    assert len(judge.cache) == 1  # second call hit cache, not added again


# ---------------------------------------------------------------------------
# Error case — missing task
# ---------------------------------------------------------------------------


def test_runner_missing_task_returns_error():
    """Requesting a nonexistent task returns an error dict."""
    tasks_dir = Path("evals/tasks")
    if not tasks_dir.exists():
        pytest.skip("evals/tasks/ directory not found")
    runner = EvalRunner(tasks_dir=tasks_dir, results_dir=Path("evals/results"))
    result = runner.run_one("nonexistent_task_name")
    assert "error" in result
