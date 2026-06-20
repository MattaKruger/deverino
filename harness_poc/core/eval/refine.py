"""evaluate_and_refine — iterative improvement wrapper for skill outputs.

Phase 3.3: Implements the Anthropic evaluator-optimizer pattern:
generation → evaluation → feedback → regeneration.

Usage::

    from harness_poc.core.eval.refine import evaluate_and_refine

    result = evaluate_and_refine(
        skill_name="spec_writer",
        skill_input={"objective": "Design a caching layer"},
        max_iterations=3,
    )
"""

from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

from harness_poc.core.eval.judge import JudgeEvaluator, JudgeResult
from harness_poc.core.eval.task import EvalTask, EvalTaskEval

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)


def evaluate_and_refine(
    skill_name: str,
    skill_input: dict[str, Any],
    *,
    execute_fn: Callable[[str, dict[str, Any]], dict[str, Any]],
    max_iterations: int = 3,
    min_score: float = 3.0,
) -> dict[str, Any]:
    """Run a skill with iterative critique and refinement.

    Args:
        skill_name: Name of the skill being called (for logging/judging).
        skill_input: Arguments to pass to the skill.
        execute_fn: Function that executes the skill and returns its result.
            Signature: ``(skill_name: str, arguments: dict) -> dict[str, Any]``
            The returned dict should have ``content`` and ``artifacts`` keys.
        max_iterations: Maximum refinement attempts.
        min_score: Score threshold for early exit.

    Returns:
        Best skill result with added ``_refinement_history`` key containing
        scores and critiques from each attempt.
    """
    history: list[dict[str, Any]] = []
    best_output: dict[str, Any] | None = None
    best_score = 0.0

    for attempt in range(max_iterations):
        logger.info(
            "evaluate_and_refine: attempt %d/%d for %s", attempt + 1, max_iterations, skill_name
        )

        # Execute
        result = execute_fn(skill_name, dict(skill_input))
        output = _extract_output(result)

        # Evaluate
        task = EvalTask(
            name=skill_name,
            description=str(skill_input.get("objective", "")),
            category="refinement",
            input={"prompt": str(skill_input.get("objective", "")), "context": {}},
            evaluation=EvalTaskEval(
                type="llm_judge",
                rubric="1-5 scale on completeness, correctness, and quality",
                min_score=min_score,
            ),
        )

        judge = JudgeEvaluator()
        eval_result: JudgeResult = judge.evaluate(task, output)
        score = eval_result.score

        history.append(
            {
                "attempt": attempt + 1,
                "score": score,
                "passed": eval_result.passed,
                "critique": eval_result.explanation,
            }
        )

        # Track best
        if best_output is None or score > best_score:
            best_output = dict(result)
            best_score = score

        # Early exit
        if eval_result.passed:
            logger.info(
                "evaluate_and_refine: passed at attempt %d (score=%.1f)", attempt + 1, score
            )
            break

        # Inject critique into input for next attempt
        if attempt < max_iterations - 1:
            skill_input = _inject_critique(skill_input, eval_result.explanation)

    # Attach history to best result
    if best_output is None:
        best_output = {"content": "", "artifacts": {}}
    best_output["_refinement_history"] = history

    return best_output


def _extract_output(result: dict[str, Any]) -> str:
    """Extract the output text from a skill result dict."""
    # Prefer non-empty content
    if isinstance(result.get("content"), str) and result["content"].strip():
        return result["content"]
    if isinstance(result.get("artifacts"), dict):
        for key in ("model_output", "output", "result", "summary"):
            val = result["artifacts"].get(key)
            if isinstance(val, str) and val.strip():
                return val
            if isinstance(val, dict) and isinstance(val.get("summary"), str):
                return val["summary"]
    return str(result)


def _inject_critique(input_dict: dict[str, Any], critique: str) -> dict[str, Any]:
    """Add critique feedback to the input for the next iteration."""
    modified = dict(input_dict)

    # Add critique as a prefix to the objective
    objective = modified.get("objective", "")
    if isinstance(objective, str):
        modified["objective"] = f"{objective}\n\n[Feedback from previous attempt: {critique}]"

    # Add critique to context
    context = modified.get("context", "")
    if isinstance(context, str):
        modified["context"] = (
            f"{context}\n[Critique: {critique}]" if context else f"[Critique: {critique}]"
        )
    elif isinstance(context, dict):
        context = dict(context)
        context["_critique"] = critique
        modified["context"] = context

    return modified
