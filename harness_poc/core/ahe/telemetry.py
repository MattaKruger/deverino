"""AHE Stage 1 — Telemetry aggregation.

Queries both event tables — DbContextMapEvent for context map signals,
DbStateEvent for task-level signals — and aggregates trajectory-level
data into a TelemetrySummary.

Telemetry sources (corrected from spec §5.4 after codebase verification):
- Context map: MapEntryReferenced, MapEntryEvicted, MapEntryInserted
  (DbContextMapEvent, per-corpus)
- Delegation: SubAgentDispatched, SubAgentCompleted (DbStateEvent)
  DelegateTaskCompleted is deprecated (specs/20260613-sub-agent-system.md).
  SubAgentCompleted carries the status field.
- Gates: GateCompleted, GatePassed, GateFailed (DbStateEvent)
- Tokens: LLMActionEmitted (DbStateEvent)
  AgentTurnRecorded has no token fields; LLMActionEmitted has
  tokens_used, input_tokens, output_tokens, billable_tokens.
- Execution: ExecutionCompleted, SpecCommitted (DbStateEvent)

See docs/superpowers/specs/2026-06-22-ahe-evolution-agent-design.md §5.2 Stage 1.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlmodel import Session, col, select

from harness_poc.core.context_map.sections import SECTION_MAP
from harness_poc.core.storage import DbStateEvent
from harness_poc.core.storage.models import DbContextMapEvent

if TYPE_CHECKING:
    from harness_poc.core.storage.database import BlackboardDatabase

logger = logging.getLogger(__name__)


# ─── Data model ───────────────────────────────────────────────────────────


@dataclass
class ContextMapTelemetry:
    """Context map event signals, aggregated per observation_type and section."""

    references_by_type: dict[str, int] = field(default_factory=dict)
    evictions_by_type: dict[str, int] = field(default_factory=dict)
    insertions_by_type: dict[str, int] = field(default_factory=dict)
    eviction_reasons: dict[str, int] = field(default_factory=dict)
    references_by_section: dict[str, int] = field(default_factory=dict)
    total: int = 0


@dataclass
class DelegationTelemetry:
    """Sub-agent lifecycle signals from SubAgentDispatched + SubAgentCompleted."""

    dispatched: int = 0
    completed: int = 0
    failed: int = 0
    cancelled: int = 0
    by_persona: dict[str, int] = field(default_factory=dict)


@dataclass
class GateTelemetry:
    """Verification gate signals from GateCompleted, GatePassed, GateFailed."""

    gate_completed_passed: int = 0
    gate_completed_failed: int = 0
    gate_passed: int = 0
    gate_failed: int = 0


@dataclass
class TokenTelemetry:
    """Token usage from LLMActionEmitted."""

    total_input: int = 0
    total_output: int = 0
    total_billable: int = 0
    by_model: dict[str, int] = field(default_factory=dict)


@dataclass
class ExecutionTelemetry:
    """Execution and spec commit signals."""

    executions_total: int = 0
    all_passed: int = 0
    specs_committed: int = 0
    spec_failure_count: int = 0


@dataclass
class TelemetrySummary:
    """Aggregated telemetry for one AHE cycle."""

    cycle: int
    corpus_key: str
    window_start: str
    window_end: str
    window_days: int
    context_map: ContextMapTelemetry = field(default_factory=ContextMapTelemetry)
    delegation: DelegationTelemetry = field(default_factory=DelegationTelemetry)
    gates: GateTelemetry = field(default_factory=GateTelemetry)
    tokens: TokenTelemetry = field(default_factory=TokenTelemetry)
    execution: ExecutionTelemetry = field(default_factory=ExecutionTelemetry)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ─── Public API ───────────────────────────────────────────────────────────


def aggregate_telemetry(
    db: BlackboardDatabase,
    corpus_key: str,
    *,
    window_days: int = 7,
) -> TelemetrySummary:
    """Run Stage 1: aggregate telemetry from both event tables.

    Returns a TelemetrySummary. Does not persist — call persist_telemetry()
    to write it to the blackboard as ahe:telemetry:{cycle}.
    """
    now = datetime.now(tz=UTC)
    cutoff = (now - timedelta(days=window_days)).isoformat(timespec="seconds")
    cycle = db.get_cycle(corpus_key)

    summary = TelemetrySummary(
        cycle=cycle,
        corpus_key=corpus_key,
        window_start=cutoff,
        window_end=now.isoformat(timespec="seconds"),
        window_days=window_days,
    )

    summary.context_map = _query_context_map_events(db, corpus_key, cutoff)
    summary.delegation = _query_delegation_events(db, cutoff)
    summary.gates = _query_gate_events(db, cutoff)
    summary.tokens = _query_token_events(db, cutoff)
    summary.execution = _query_execution_events(db, cutoff)

    logger.info(
        "AHE telemetry aggregated: cycle=%d corpus=%s context_map_events=%d",
        cycle,
        corpus_key,
        summary.context_map.total,
    )
    return summary


def persist_telemetry(
    db: BlackboardDatabase,
    session_id: str,
    summary: TelemetrySummary,
) -> str:
    """Write telemetry summary to blackboard as ahe:telemetry:{cycle}.

    Returns the blackboard key. Uses write_memory (session-scoped).
    Cross-cycle accumulation requires a persistent session strategy —
    see spec §5.3, deferred to Phase 4.
    """
    key = f"ahe:telemetry:{summary.cycle}"
    db.write_memory(session_id, key, summary.to_dict())
    return key


# ─── Context map event queries (DbContextMapEvent) ────────────────────────


def _section_to_type_map() -> dict[str, str]:
    """Build reverse section -> observation_type mapping (from calibrate.py:229)."""
    reverse: dict[str, str] = {}
    for obs_type, sec in SECTION_MAP.items():
        if sec not in reverse:
            reverse[sec] = obs_type
    return reverse


def _query_context_map_events(
    db: BlackboardDatabase,
    corpus_key: str,
    cutoff: str,
) -> ContextMapTelemetry:
    result = ContextMapTelemetry()
    section_to_type = _section_to_type_map()

    with Session(db.engine) as session:
        rows = session.exec(
            select(DbContextMapEvent)
            .where(DbContextMapEvent.corpus_key == corpus_key)
            .where(DbContextMapEvent.timestamp >= cutoff)
        ).all()

    for row in rows:
        try:
            payload = json.loads(row.payload) if isinstance(row.payload, str) else row.payload
        except json.JSONDecodeError, TypeError:
            continue

        etype = row.event_type
        section = payload.get("section", "")
        result.total += 1

        if etype == "map_entry_referenced":
            obs_type = payload.get("observation_type", "") or section_to_type.get(
                section, "insight"
            )
            result.references_by_type[obs_type] = result.references_by_type.get(obs_type, 0) + 1
            if section:
                result.references_by_section[section] = (
                    result.references_by_section.get(section, 0) + 1
                )

        elif etype == "map_entry_evicted":
            obs_type = section_to_type.get(section, "insight")
            result.evictions_by_type[obs_type] = result.evictions_by_type.get(obs_type, 0) + 1
            reason = payload.get("reason", "")
            reason_key = reason.split("@")[0] if reason else "unknown"
            result.eviction_reasons[reason_key] = result.eviction_reasons.get(reason_key, 0) + 1

        elif etype == "map_entry_inserted":
            obs_type = payload.get("observation_type", "")
            result.insertions_by_type[obs_type] = result.insertions_by_type.get(obs_type, 0) + 1

    return result


# ─── State event queries (DbStateEvent) ───────────────────────────────────


def _extract_payload(row: DbStateEvent) -> dict[str, Any]:
    """Extract inner payload from DbStateEvent row.

    EventStore.persist() wraps the event as {"event_type": ..., "payload": {...}}.
    """
    outer = row.payload
    if not isinstance(outer, dict):
        return {}
    inner = outer.get("payload")
    return inner if isinstance(inner, dict) else outer


def _query_delegation_events(db: BlackboardDatabase, cutoff: str) -> DelegationTelemetry:
    result = DelegationTelemetry()
    with Session(db.engine) as session:
        rows = session.exec(
            select(DbStateEvent)
            .where(col(DbStateEvent.event_type).in_(["SubAgentDispatched", "SubAgentCompleted"]))
            .where(DbStateEvent.created_at >= cutoff)
        ).all()

    for row in rows:
        inner = _extract_payload(row)

        if row.event_type == "SubAgentDispatched":
            result.dispatched += 1
            persona = inner.get("persona", "unknown")
            result.by_persona[persona] = result.by_persona.get(persona, 0) + 1

        elif row.event_type == "SubAgentCompleted":
            status = inner.get("status", "")
            if status in ("success", "completed"):
                result.completed += 1
            elif status == "failed":
                result.failed += 1
            elif status == "cancelled":
                result.cancelled += 1

    return result


def _query_gate_events(db: BlackboardDatabase, cutoff: str) -> GateTelemetry:
    result = GateTelemetry()
    with Session(db.engine) as session:
        rows = session.exec(
            select(DbStateEvent)
            .where(col(DbStateEvent.event_type).in_(["GateCompleted", "GatePassed", "GateFailed"]))
            .where(DbStateEvent.created_at >= cutoff)
        ).all()

    for row in rows:
        inner = _extract_payload(row)

        if row.event_type == "GateCompleted":
            if inner.get("passed", False):
                result.gate_completed_passed += 1
            else:
                result.gate_completed_failed += 1
        elif row.event_type == "GatePassed":
            result.gate_passed += 1
        elif row.event_type == "GateFailed":
            result.gate_failed += 1

    return result


def _query_token_events(db: BlackboardDatabase, cutoff: str) -> TokenTelemetry:
    result = TokenTelemetry()
    with Session(db.engine) as session:
        rows = session.exec(
            select(DbStateEvent)
            .where(DbStateEvent.event_type == "LLMActionEmitted")
            .where(DbStateEvent.created_at >= cutoff)
        ).all()

    for row in rows:
        inner = _extract_payload(row)
        result.total_input += int(inner.get("input_tokens", 0))
        result.total_output += int(inner.get("output_tokens", 0))
        result.total_billable += int(inner.get("billable_tokens", 0))
        model = inner.get("model", "unknown")
        result.by_model[model] = result.by_model.get(model, 0) + int(
            inner.get("billable_tokens", 0)
        )

    return result


def _query_execution_events(db: BlackboardDatabase, cutoff: str) -> ExecutionTelemetry:
    result = ExecutionTelemetry()
    with Session(db.engine) as session:
        rows = session.exec(
            select(DbStateEvent)
            .where(col(DbStateEvent.event_type).in_(["ExecutionCompleted", "SpecCommitted"]))
            .where(DbStateEvent.created_at >= cutoff)
        ).all()

    for row in rows:
        inner = _extract_payload(row)

        if row.event_type == "ExecutionCompleted":
            result.executions_total += 1
            if inner.get("all_passed", False):
                result.all_passed += 1
        elif row.event_type == "SpecCommitted":
            result.specs_committed += 1
            result.spec_failure_count += int(inner.get("failure_count", 0))

    return result
