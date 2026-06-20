"""Evaluation infrastructure for measuring agent performance.

Phase 2 of the Deverino hardening plan establishes a benchmark suite
that gates every change with regression detection.

Exports:
    EvalRunner: Loads tasks, runs harness, scores outputs.
    JudgeEvaluator: LLM-as-judge scoring with rubric support.
    EvalTask: Pydantic model for task definitions.
"""

from harness_poc.core.eval.judge import JudgeEvaluator
from harness_poc.core.eval.runner import EvalRunner
from harness_poc.core.eval.task import EvalTask

__all__ = ["EvalRunner", "EvalTask", "JudgeEvaluator"]
