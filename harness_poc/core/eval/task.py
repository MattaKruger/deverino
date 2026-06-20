"""EvalTask — Pydantic model for evaluation task definitions.

Loads from YAML files in ``evals/tasks/``. Each task specifies a
representative problem the harness should solve, plus evaluation
criteria for automated scoring.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class EvalTaskInput(BaseModel):
    """Input specification for an eval task.

    Files can be inline content or paths to load. Additional context
    is free-form key/value data passed to the agent.
    """

    prompt: str = ""  # The explicit prompt to give the agent
    context: dict[str, Any] = Field(default_factory=dict)


class EvalTaskEval(BaseModel):
    """Evaluation configuration for a task."""

    type: str = "llm_judge"  # "llm_judge" | "trait_check" | "binary"
    rubric: str = ""
    expected_traits: list[str] = Field(default_factory=list)
    min_score: float = 3.0
    min_traits: int = 0  # how many traits must be present


class EvalTask(BaseModel):
    """A single evaluation task loaded from YAML."""

    name: str
    description: str = ""
    category: str = "general"
    input: EvalTaskInput = Field(default_factory=EvalTaskInput)
    evaluation: EvalTaskEval = Field(default_factory=EvalTaskEval)

    @classmethod
    def from_yaml(cls, path: Path) -> EvalTask:
        """Load a task from a YAML file."""
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"Expected YAML mapping in {path}")
        return cls.model_validate(data)

    @classmethod
    def load_all(cls, tasks_dir: Path) -> list[EvalTask]:
        """Load all YAML task files from a directory."""
        if not tasks_dir.exists():
            return []
        tasks: list[EvalTask] = []
        for task_file in sorted(tasks_dir.glob("*.yaml")):
            try:
                tasks.append(cls.from_yaml(task_file))
            except Exception as exc:
                import logging

                logging.getLogger(__name__).warning(
                    "Failed to load eval task %s: %s", task_file, exc
                )
        return tasks
