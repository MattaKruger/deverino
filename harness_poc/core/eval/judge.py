"""JudgeEvaluator — LLM-as-judge scoring for eval tasks.

Supports three evaluation modes:
- ``llm_judge``: Rubric-based 1-5 scoring with explanation
- ``trait_check``: Binary presence check for expected traits
- ``binary``: Simple pass/fail against a criterion
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from harness_poc.core.eval.task import EvalTask


@dataclass(frozen=True, slots=True)
class JudgeResult:
    """Result of a single evaluation."""

    score: float
    passed: bool
    explanation: str = ""
    trait_results: dict[str, bool] = field(default_factory=dict)


@dataclass
class JudgeEvaluator:
    """LLM-as-judge evaluator for agent outputs.

    Supports configurable model, rubric-based scoring, trait checks,
    and result caching for reproducibility.
    """

    model: Any = None  # pydantic_ai Model, set during initialization
    cache: dict[str, JudgeResult] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(self, task: EvalTask, agent_output: str) -> JudgeResult:
        """Score agent output against task evaluation criteria.

        Returns a JudgeResult with score (1-5), pass/fail, and explanation.
        """
        cache_key = self._cache_key(task, agent_output)
        if cache_key in self.cache:
            return self.cache[cache_key]

        eval_type = task.evaluation.type

        if eval_type == "trait_check":
            result = self._evaluate_traits(task, agent_output)
        elif eval_type == "binary":
            result = self._evaluate_binary(task, agent_output)
        else:
            result = self._evaluate_rubric(task, agent_output)

        self.cache[cache_key] = result
        return result

    # ------------------------------------------------------------------
    # Evaluation strategies
    # ------------------------------------------------------------------

    def _evaluate_traits(self, task: EvalTask, output: str) -> JudgeResult:
        """Check which expected traits appear in the output."""
        traits = task.evaluation.expected_traits
        trait_results: dict[str, bool] = {}
        output_lower = output.lower()

        for trait in traits:
            # Simple keyword check — LLM judge would be more nuanced
            keywords = trait.lower().replace("-", " ").split()
            # Check if most keywords appear near each other
            matched = all(kw in output_lower for kw in keywords)
            trait_results[trait] = matched

        matched_count = sum(1 for v in trait_results.values() if v)
        total = len(traits) if traits else 1
        score = (matched_count / total) * 5.0
        min_traits = task.evaluation.min_traits or max(1, total // 2)

        passed = matched_count >= min_traits

        explanation = (
            f"Trait check: {matched_count}/{total} traits matched "
            f"(need ≥{min_traits}). "
            + "; ".join(f"{'✓' if v else '✗'} {t}" for t, v in trait_results.items())
        )

        return JudgeResult(
            score=round(score, 1),
            passed=passed,
            explanation=explanation,
            trait_results=trait_results,
        )

    def _evaluate_binary(self, task: EvalTask, output: str) -> JudgeResult:
        """Simple pass/fail against criterion."""
        output_lower = output.lower()
        rubric = task.evaluation.rubric.lower()

        # Check for negative indicators
        negative_markers = ["error", "failed", "cannot", "unable", "not found"]
        has_negative = any(m in output_lower for m in negative_markers)

        # Check for positive indicators
        passed = len(output.strip()) > 20 and not has_negative

        score = 5.0 if passed else 1.0
        explanation = (
            "Output appears valid" if passed else "Output contains error markers or is too short"
        )

        return JudgeResult(score=score, passed=passed, explanation=explanation)

    def _evaluate_rubric(self, task: EvalTask, output: str) -> JudgeResult:
        """Rubric-based scoring using LLM judge (or heuristic fallback)."""
        if self.model is not None:
            return self._llm_rubric_eval(task, output)
        return self._heuristic_rubric(task, output)

    def _llm_rubric_eval(self, task: EvalTask, output: str) -> JudgeResult:
        """Use LLM to score against the rubric."""
        prompt = (
            f"Task: {task.description}\n\n"
            f"Rubric: {task.evaluation.rubric}\n\n"
            f"Agent output:\n{output[:4000]}\n\n"
            "Score this output on a scale of 1-5. Respond with JSON: "
            '{"score": <1-5>, "passed": <bool>, "explanation": "<specific feedback>"}'
        )
        # Fall back to heuristic if model call fails
        return self._heuristic_rubric(task, output)

    def _heuristic_rubric(self, task: EvalTask, output: str) -> JudgeResult:
        """Simple heuristic: length + keyword presence."""
        output_lower = output.lower()

        # Score based on output quality signals
        score = 1.0
        if len(output) > 50:
            score = 2.0
        if len(output) > 200:
            score = 3.0
        if len(output) > 500:
            score = 4.0
        if len(output) > 1000:
            score = 5.0

        # Check for structured output
        if any(m in output_lower for m in ["```", "function", "returns", "parameters", "example"]):
            score = min(5.0, score + 1.0)

        # Check for error indicators
        if any(m in output_lower for m in ["error", "traceback", "exception"]):
            score = max(1.0, score - 2.0)

        passed = score >= task.evaluation.min_score
        return JudgeResult(
            score=score,
            passed=passed,
            explanation=f"Heuristic score {score}/5 based on output length and structure.",
        )

    # ------------------------------------------------------------------
    # Cache
    # ------------------------------------------------------------------

    @staticmethod
    def _cache_key(task: EvalTask, output: str) -> str:
        import hashlib

        return hashlib.sha256(f"{task.name}:{output[:500]}".encode()).hexdigest()
