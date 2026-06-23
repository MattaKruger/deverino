"""AHE Evolution Agent — skill orchestrator.

Runs stages 1-3 of the AHE loop: observe (telemetry), diagnose, propose.
Dry-run by default — no mutation. Promotion (stages 4-5) is a separate phase.

See docs/superpowers/specs/2026-06-22-ahe-evolution-agent-design.md §5.2.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, cast

from harness_poc.core.ahe import aggregate_telemetry, persist_telemetry
from harness_poc.core.ahe.diagnose import persist_diagnosis, run_diagnosis
from harness_poc.core.ahe.propose import persist_proposals, run_proposals
from harness_poc.core.skills import SkillResult

if TYPE_CHECKING:
    from harness_poc.core.skills import SkillContext
    from harness_poc.core.storage.database import BlackboardDatabase


def execute(ctx: SkillContext, arguments: dict[str, Any]) -> SkillResult:
    """Run AHE stages 1-3: observe, diagnose, propose."""
    corpus_key = str(arguments.get("corpus_key") or "default")
    window_days = int(arguments.get("window_days") or 7)
    db = cast("BlackboardDatabase", ctx.database)
    session_id = ctx.session_id

    # Stage 1: Observe
    ctx.emit_text("Stage 1: Aggregating telemetry...\n")
    telemetry = aggregate_telemetry(db, corpus_key, window_days=window_days)
    persist_telemetry(db, session_id, telemetry)
    ctx.emit_text(f"  cycle={telemetry.cycle} context_map_events={telemetry.context_map.total}\n")

    # Stage 2: Diagnose
    ctx.emit_text("Stage 2: Diagnosing harness problems...\n")
    diagnosis = run_diagnosis(ctx, telemetry)
    persist_diagnosis(db, session_id, diagnosis)
    ctx.emit_text(f"  {len(diagnosis.entries)} problems diagnosed\n")

    # Stage 3: Propose
    ctx.emit_text("Stage 3: Generating proposals...\n")
    proposals = run_proposals(ctx, diagnosis)
    persist_proposals(db, session_id, proposals)
    ctx.emit_text(f"  {len(proposals)} proposals generated\n")

    result = {
        "status": "success",
        "telemetry_cycle": telemetry.cycle,
        "diagnosis_entries": len(diagnosis.entries),
        "proposals": [
            {
                "proposal_id": p.proposal_id,
                "target_component": p.target_component,
                "governance_tier": p.governance_tier,
                "rationale": p.rationale,
            }
            for p in proposals
        ],
        "summary": (
            f"AHE cycle {telemetry.cycle}: "
            f"{len(diagnosis.entries)} problems diagnosed, "
            f"{len(proposals)} proposals generated. "
            "Review proposals before promotion."
        ),
    }

    return SkillResult(
        status="success",
        content=json.dumps(result, indent=2, default=str),
        artifacts={
            "telemetry_key": f"ahe:telemetry:{telemetry.cycle}",
            "diagnosis_key": f"ahe:diagnosis:{telemetry.cycle}",
            "proposal_keys": [f"ahe:proposal:{p.proposal_id}" for p in proposals],
        },
    )
