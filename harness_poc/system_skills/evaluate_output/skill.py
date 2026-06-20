"""evaluate_output — LLM-as-judge skill for self-assessment.

Returns structured evaluation with score, pass/fail, specific critique,
and improvement suggestions. Used by the Reflexion loop and the
evaluate_and_refine wrapper.
"""

from __future__ import annotations

from typing import Any

from harness_poc.core.skills import SkillResult

# Import the JudgeEvaluator from the eval module
from harness_poc.core.eval.judge import JudgeEvaluator, JudgeResult
from harness_poc.core.eval.task import EvalTask, EvalTaskEval


def execute(ctx: Any, arguments: dict[str, Any]) -> SkillResult:
    """Evaluate an agent's output against an objective.

    Args:
        objective: The original goal/task description.
        output: The agent's output text to evaluate.
        context: Optional additional context.
        criteria: Optional list of specific criteria to check.

    Returns:
        SkillResult with score, passed, critique, suggestions in artifacts.
    """
    objective = str(arguments.get("objective", ""))
    output = str(arguments.get("output", ""))
    context = str(arguments.get("context", ""))
    criteria = arguments.get("criteria", [])

    if not objective or not output:
        return SkillResult(
            status="failed",
            content="Missing required arguments: objective and output are required.",
        )

    # Build evaluation
    full_output = output
    if context:
        full_output = f"Context: {context}\n\nOutput: {output}"

    # Use trait check if criteria provided, otherwise rubric eval
    eval_type = "trait_check" if criteria else "llm_judge"

    task = EvalTask(
        name="evaluate_output",
        description=objective,
        category="self_eval",
        input={"prompt": objective, "context": {"context": context} if context else {}},
        evaluation=EvalTaskEval(
            type=eval_type,
            rubric="1-5 scale on accuracy, completeness, and actionability",
            expected_traits=list(criteria) if criteria else [],
            min_score=3.0,
            min_traits=max(1, len(criteria) // 2) if criteria else 0,
        ),
    )

    judge = JudgeEvaluator()
    result: JudgeResult = judge.evaluate(task, full_output)

    return SkillResult(
        status="success" if result.passed else "failed",
        content=(
            f"Evaluation: score={result.score}/5, passed={result.passed}\n"
            f"Critique: {result.explanation}"
        ),
        artifacts={
            "score": result.score,
            "passed": result.passed,
            "critique": result.explanation,
            "suggestions": _extract_suggestions(result.explanation),
            "trait_results": result.trait_results,
        },
    )


def _extract_suggestions(explanation: str) -> list[str]:
    """Extract actionable suggestions from the explanation text."""
    suggestions: list[str] = []
    # Simple heuristic: split on numbered items or bullet points
    for line in explanation.split("\n"):
        stripped = line.strip()
        if stripped and (stripped[0].isdigit() and ". " in stripped[:4]):
            suggestions.append(stripped[stripped.index(". ") + 2 :])
        elif stripped.startswith("- "):
            suggestions.append(stripped[2:])
    if not suggestions:
        suggestions.append(explanation[:200])
    return suggestions[:3]
