"""EvalRunner — load tasks, run harness, score results.

Produces JSON reports in ``evals/results/`` and can gate CI via
non-zero exit code when any task fails ``min_score``.
"""

from __future__ import annotations

import json as _json
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from harness_poc.core.eval.judge import JudgeEvaluator, JudgeResult
from harness_poc.core.eval.task import EvalTask

if TYPE_CHECKING:
    from collections.abc import Callable


logger = logging.getLogger(__name__)


@dataclass
class EvalReport:
    """Aggregate report for an eval run."""

    run_id: str
    timestamp: str
    tasks_total: int
    tasks_passed: int
    tasks_failed: int
    average_score: float
    results: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "timestamp": self.timestamp,
            "tasks_total": self.tasks_total,
            "tasks_passed": self.tasks_passed,
            "tasks_failed": self.tasks_failed,
            "average_score": round(self.average_score, 2),
            "results": self.results,
        }


@dataclass
class EvalRunner:
    """Run evaluation tasks through the harness.

    Args:
        tasks_dir: Directory containing YAML task definitions.
        results_dir: Directory for writing JSON result reports.
        judge: JudgeEvaluator instance for scoring.
        run_fn: Callable that runs a task and returns agent output.
            Signature: ``(prompt: str, context: dict) -> str``
    """

    tasks_dir: Path = Path("evals/tasks")
    results_dir: Path = Path("evals/results")
    judge: JudgeEvaluator = field(default_factory=JudgeEvaluator)
    run_fn: Callable[[str, dict[str, Any]], str] | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_all(self, *, category: str | None = None) -> EvalReport:
        """Run all tasks and return an aggregate report."""
        tasks = EvalTask.load_all(self.tasks_dir)
        if category:
            tasks = [t for t in tasks if t.category == category]

        if not tasks:
            return EvalReport(
                run_id="none",
                timestamp="",
                tasks_total=0,
                tasks_passed=0,
                tasks_failed=0,
                average_score=0.0,
            )

        run_id = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        timestamp = datetime.now(UTC).isoformat()

        results: list[dict[str, Any]] = []
        scores: list[float] = []
        passed_count = 0
        failed_count = 0

        for task in tasks:
            logger.info("Running eval task: %s", task.name)
            result = self._run_one(task)
            results.append(result)
            scores.append(result["score"])
            if result["passed"]:
                passed_count += 1
            else:
                failed_count += 1

        avg = sum(scores) / len(scores) if scores else 0.0

        report = EvalReport(
            run_id=run_id,
            timestamp=timestamp,
            tasks_total=len(tasks),
            tasks_passed=passed_count,
            tasks_failed=failed_count,
            average_score=avg,
            results=results,
        )

        # Write report
        self._write_report(report)

        return report

    def run_one(self, task_name: str) -> dict[str, Any]:
        """Run a single named task."""
        tasks = EvalTask.load_all(self.tasks_dir)
        task = next((t for t in tasks if t.name == task_name), None)
        if task is None:
            return {"error": f"Task not found: {task_name}"}
        return self._run_one(task)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run_one(self, task: EvalTask) -> dict[str, Any]:
        """Execute one task and score it."""
        start = time.monotonic()

        # Pre-read referenced files so the agent can answer without tool calls.
        # DeepSeek V4 Flash defaults to search tools and ignores direct read
        # instructions, making file-based tasks time out.
        prompt = self._build_rich_prompt(task)

        # Execute the agent
        agent_output = ""
        error: str | None = None
        try:
            if self.run_fn is not None:
                agent_output = self.run_fn(prompt, task.input.context)
            else:
                agent_output = self._default_run(task)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            logger.exception("Eval task %s failed", task.name)

        elapsed = time.monotonic() - start

        # Score
        if error:
            judge_result = JudgeResult(score=0.0, passed=False, explanation=error)
        else:
            judge_result = self.judge.evaluate(task, agent_output)

        return {
            "task": task.name,
            "category": task.category,
            "score": judge_result.score,
            "passed": judge_result.passed,
            "explanation": judge_result.explanation,
            "trait_results": judge_result.trait_results,
            "elapsed_seconds": round(elapsed, 2),
            "error": error,
            "output_preview": agent_output[:500],
        }

    @staticmethod
    def _build_rich_prompt(task: EvalTask) -> str:
        """Build a prompt with pre-read file content injected as context.

        When the task context references files (``context.file`` or
        ``context.files``), pre-read them and append their content so
        the agent can answer directly without tool calls.
        """
        prompt = task.input.prompt
        ctx = task.input.context

        # Collect file paths from context
        paths: list[str] = []
        if isinstance(ctx.get("file"), str):
            paths.append(ctx["file"])
        if isinstance(ctx.get("files"), list):
            for f in ctx["files"]:
                if isinstance(f, str):
                    paths.append(f)

        if not paths:
            return prompt

        # Pre-read files and inject content
        file_contents: list[str] = []
        for rel_path in paths:
            file_path = Path(rel_path)
            if not file_path.exists():
                file_contents.append(f"[File not found: {rel_path}]")
                continue
            try:
                content = file_path.read_text(encoding="utf-8")
                # Truncate to avoid blowing context window
                max_chars = 12000
                if len(content) > max_chars:
                    content = content[:max_chars] + "\n... [truncated]"
                file_contents.append(f"--- {rel_path} ---\n{content}\n--- end {rel_path} ---")
            except Exception:
                file_contents.append(f"[Could not read: {rel_path}]")

        if file_contents:
            prompt += "\n\n" + "\n\n".join(file_contents)
            prompt += (
                "\n\nAnswer the question above using the provided file content. "
                "Do not call any tools — all information you need is above."
            )

        return prompt

    @staticmethod
    def _default_run(task: EvalTask) -> str:
        """Default (offline) runner — returns a placeholder.

        In production, the harness is wired via the CLI with a real model.
        """
        return (
            f"Placeholder output for task '{task.name}': "
            f"Run with --live to execute through the harness."
        )

    def _write_report(self, report: EvalReport) -> None:
        """Write the report JSON to the results directory."""
        self.results_dir.mkdir(parents=True, exist_ok=True)
        path = self.results_dir / f"{report.run_id}.json"
        path.write_text(
            _json.dumps(report.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
        )
        logger.info("Eval report written: %s", path)


# ---------------------------------------------------------------------------
# Factory for CLI usage
# ---------------------------------------------------------------------------


def create_eval_runner(
    tasks_dir: str = "evals/tasks",
    results_dir: str = "evals/results",
    run_fn: Callable[[str, dict[str, Any]], str] | None = None,
) -> EvalRunner:
    """Create an EvalRunner with default configuration.

    Args:
        tasks_dir: Path to task YAML directory.
        results_dir: Path for writing result reports.
        run_fn: Function that executes a prompt through the harness.

    Returns:
        Configured EvalRunner ready to call ``run_all()``.
    """
    return EvalRunner(
        tasks_dir=Path(tasks_dir),
        results_dir=Path(results_dir),
        judge=JudgeEvaluator(),
        run_fn=run_fn,
    )
