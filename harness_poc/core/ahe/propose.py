"""AHE Stage 3 — Proposal generation.

Delegates proposal generation to a harness_engineer subagent via delegate_task.
The subagent receives the diagnosis and proposes specific harness revisions
with governance tier classification.

See docs/superpowers/specs/2026-06-22-ahe-evolution-agent-design.md §5.2 Stage 3.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

from harness_poc.system_skills.delegate_task.skill import execute as delegate_execute

if TYPE_CHECKING:
    from harness_poc.core.ahe.diagnose import Diagnosis
    from harness_poc.core.skills import SkillContext, SkillResult
    from harness_poc.core.storage.database import BlackboardDatabase

logger = logging.getLogger(__name__)


@dataclass
class Proposal:
    """A candidate harness revision."""

    proposal_id: str
    cycle: int
    target_component: str
    observed_problem: str
    proposed_change: str
    governance_tier: str  # "auto" | "hitl"
    rationale: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def run_proposals(ctx: SkillContext, diagnosis: Diagnosis) -> list[Proposal]:
    """Run Stage 3: delegate proposal generation to harness_engineer subagent."""
    objective = (
        "Based on this diagnosis, propose specific harness revisions.\n\n"
        "For each proposal, specify:\n"
        "- target_component: which harness component to revise\n"
        "- observed_problem: what diagnosed problem this addresses\n"
        "- proposed_change: the specific revision (config diff or rule update)\n"
        "- governance_tier: 'auto' for low-risk, 'hitl' for high-risk\n"
        "- rationale: why this change should improve the harness\n\n"
        "Return proposals as a list in artifacts['proposals']. "
        "Each proposal must have all five keys above."
    )

    result = delegate_execute(
        ctx,
        {
            "persona": "harness_engineer",
            "objective": objective,
            "context": json.dumps(diagnosis.to_dict(), indent=2, default=str),
            "memory_key": f"ahe:proposals:{diagnosis.cycle}",
        },
    )

    return _parse_proposal_result(result, diagnosis.cycle)


def _parse_proposal_result(result: SkillResult, cycle: int) -> list[Proposal]:
    """Extract proposals from delegate_task SkillResult."""
    proposals: list[Proposal] = []

    try:
        data = json.loads(result.content)
    except json.JSONDecodeError, TypeError:
        logger.warning("Failed to parse delegate_task result as JSON")
        return proposals

    if data.get("status") in ("failed", "blocked"):
        logger.warning("delegate_task returned status=%s", data.get("status"))

    model_output = data.get("artifacts", {}).get("model_output", {})
    subagent_artifacts = model_output.get("artifacts", {})
    proposals_raw = subagent_artifacts.get("proposals", [])

    for seq, prop_raw in enumerate(proposals_raw, start=1):
        if not isinstance(prop_raw, dict):
            continue
        proposals.append(
            Proposal(
                proposal_id=f"cycle-{cycle}-{seq:02d}",
                cycle=cycle,
                target_component=str(prop_raw.get("target_component", "")),
                observed_problem=str(prop_raw.get("observed_problem", "")),
                proposed_change=str(prop_raw.get("proposed_change", "")),
                governance_tier=str(prop_raw.get("governance_tier", "hitl")),
                rationale=str(prop_raw.get("rationale", "")),
            )
        )

    logger.info("AHE proposals generated: cycle=%d count=%d", cycle, len(proposals))
    return proposals


def persist_proposals(
    db: BlackboardDatabase,
    session_id: str,
    proposals: list[Proposal],
) -> list[str]:
    """Write each proposal to blackboard as ahe:proposal:{proposal_id}."""
    keys: list[str] = []
    for proposal in proposals:
        key = f"ahe:proposal:{proposal.proposal_id}"
        db.write_memory(session_id, key, proposal.to_dict())
        keys.append(key)
    return keys
