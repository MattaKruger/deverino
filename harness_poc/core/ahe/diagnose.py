"""AHE Stage 2 — Diagnosis.

Delegates telemetry analysis to a harness_engineer subagent via delegate_task.
The subagent receives the TelemetrySummary and attributes observed problems
to specific harness components.

See docs/superpowers/specs/2026-06-22-ahe-evolution-agent-design.md §5.2 Stage 2.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any

from harness_poc.system_skills.delegate_task.skill import execute as delegate_execute

if TYPE_CHECKING:
    from harness_poc.core.ahe.telemetry import TelemetrySummary
    from harness_poc.core.skills import SkillContext, SkillResult
    from harness_poc.core.storage.database import BlackboardDatabase

logger = logging.getLogger(__name__)


@dataclass
class DiagnosisEntry:
    """A single diagnosed problem attributed to a harness component."""

    observed_problem: str
    attributed_component: str
    evidence: str


@dataclass
class Diagnosis:
    """Diagnosis output for one AHE cycle."""

    cycle: int
    corpus_key: str
    entries: list[DiagnosisEntry] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def run_diagnosis(ctx: SkillContext, telemetry: TelemetrySummary) -> Diagnosis:
    """Run Stage 2: delegate telemetry analysis to harness_engineer subagent."""
    objective = (
        "Analyze this telemetry summary and diagnose harness-level problems.\n\n"
        "For each problem, identify:\n"
        "- observed_problem: what the telemetry shows\n"
        "- attributed_component: which harness component is responsible\n"
        "- evidence: the specific telemetry signals that triggered this\n\n"
        "Return the diagnosis entries as a list in artifacts['diagnosis_entries']. "
        "Each entry must have keys: observed_problem, attributed_component, evidence.\n"
        "Put an overall assessment in the summary field."
    )

    result = delegate_execute(
        ctx,
        {
            "persona": "harness_engineer",
            "objective": objective,
            "context": json.dumps(telemetry.to_dict(), indent=2, default=str),
            "memory_key": f"ahe:diagnosis:{telemetry.cycle}",
        },
    )

    return _parse_diagnosis_result(result, telemetry.cycle, telemetry.corpus_key)


def _parse_diagnosis_result(
    result: SkillResult,
    cycle: int,
    corpus_key: str,
) -> Diagnosis:
    """Extract Diagnosis from delegate_task SkillResult."""
    diagnosis = Diagnosis(cycle=cycle, corpus_key=corpus_key)

    try:
        data = json.loads(result.content)
    except json.JSONDecodeError, TypeError:
        logger.warning("Failed to parse delegate_task result as JSON")
        diagnosis.summary = result.content
        return diagnosis

    if data.get("status") in ("failed", "blocked"):
        logger.warning("delegate_task returned status=%s", data.get("status"))

    diagnosis.summary = data.get("summary", "")

    # delegate_task wraps output as: artifacts.model_output.artifacts
    model_output = data.get("artifacts", {}).get("model_output", {})
    subagent_artifacts = model_output.get("artifacts", {})
    entries_raw = subagent_artifacts.get("diagnosis_entries", [])

    for entry_raw in entries_raw:
        if not isinstance(entry_raw, dict):
            continue
        diagnosis.entries.append(
            DiagnosisEntry(
                observed_problem=str(entry_raw.get("observed_problem", "")),
                attributed_component=str(entry_raw.get("attributed_component", "")),
                evidence=str(entry_raw.get("evidence", "")),
            )
        )

    logger.info("AHE diagnosis complete: cycle=%d entries=%d", cycle, len(diagnosis.entries))
    return diagnosis


def persist_diagnosis(
    db: BlackboardDatabase,
    session_id: str,
    diagnosis: Diagnosis,
) -> str:
    """Write diagnosis to blackboard as ahe:diagnosis:{cycle}."""
    key = f"ahe:diagnosis:{diagnosis.cycle}"
    db.write_memory(session_id, key, diagnosis.to_dict())
    return key
