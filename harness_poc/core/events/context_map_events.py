from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ContextMapEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = Field(
        default_factory=lambda: datetime.now(tz=UTC).isoformat(timespec="seconds")
    )
    session_id: str
    corpus_key: str
    event_type: str


class CorpusIngested(ContextMapEvent):
    event_type: Literal["corpus_ingested"] = "corpus_ingested"
    corpus_name: str
    document_count: int
    total_tokens: int
    schema_hint: str | None = None


class DocumentRetrieved(ContextMapEvent):
    event_type: Literal["document_retrieved"] = "document_retrieved"
    query: str
    retrieved_doc_ids: list[str]
    retrieved_doc_titles: list[str]
    retrieval_strategy: str


class EntityReferenced(ContextMapEvent):
    event_type: Literal["entity_referenced"] = "entity_referenced"
    entity_name: str
    entity_type: str
    context: str


class SchemaDiscovered(ContextMapEvent):
    event_type: Literal["schema_discovered"] = "schema_discovered"
    schema_description: str
    example: str


class SearchFailed(ContextMapEvent):
    event_type: Literal["search_failed"] = "search_failed"
    attempted_query: str
    strategy: str
    error: str


class FactDisputed(ContextMapEvent):
    event_type: Literal["fact_disputed"] = "fact_disputed"
    previous_claim: str
    corrected_claim: str
    source_doc_id: str


class ContextualInsightDiscovered(ContextMapEvent):
    event_type: Literal["contextual_insight_discovered"] = "contextual_insight_discovered"
    insight: str
    supporting_events: list[str]
    map_section: str


class BoundaryIdentified(ContextMapEvent):
    event_type: Literal["boundary_identified"] = "boundary_identified"
    boundary_description: str
    detail: str


class ConstantDocumented(ContextMapEvent):
    event_type: Literal["constant_documented"] = "constant_documented"
    constant_summary: str
    detail: str


class ResultRecorded(ContextMapEvent):
    event_type: Literal["result_recorded"] = "result_recorded"
    result_summary: str
    detail: str


class ArchitectureInvariantObserved(ContextMapEvent):
    event_type: Literal["architecture_invariant_observed"] = (
        "architecture_invariant_observed"
    )
    invariant_summary: str
    detail: str


class MapEntryInserted(ContextMapEvent):
    """Emitted when a MapEntry appears for the first time (first_seen_cycle == cycle_n).

    Required by the §4.4 calibration job: without an insertion signal,
    "entries of this type ever materialized" can only be reconstructed from
    the current map plus eviction events, which loses entries that were
    inserted and evicted within the calibration window.
    """

    event_type: Literal["map_entry_inserted"] = "map_entry_inserted"
    entry_id: str
    entry_key: str
    section: str
    observation_type: str
    cycle_n: int


class MapEntryPromoted(ContextMapEvent):
    """DEPRECATED: promotions are an artifact of the old section-table model.

    The flat MapEntry schema has no promotion semantic.
    This class stays in the registry so historical events deserialize.
    No new MapEntryPromoted events are emitted after Track A §3.1 lands.
    See docs/superpowers/specs/2026-05-24-deterministic-cartographer-deferred-features.md §3.4.
    """

    event_type: Literal["map_entry_promoted"] = "map_entry_promoted"
    entry_id: str | None = None
    entry_key: str
    from_section: str
    to_section: str


class MapEntryEvicted(ContextMapEvent):
    event_type: Literal["map_entry_evicted"] = "map_entry_evicted"
    entry_id: str | None = None
    entry_key: str
    section: str
    reason: str  # Structured: "stale@cycle=N,age=M,type=X" or "budget@cycle=N,priority=P"
    materialization_count: int = 0


class MapEntryReferenced(ContextMapEvent):
    """Emitted (by a future wiring spec) when the agent's response cites a map entry.

    Defined here so the schema is stable; emission lives elsewhere.
    """

    event_type: Literal["map_entry_referenced"] = "map_entry_referenced"
    entry_id: str
    entry_key: str
    section: str
    cycle_n: int
    citation_context: str  # Snippet of agent output that cited the entry


CONTEXT_MAP_EVENT_REGISTRY: dict[str, type[ContextMapEvent]] = {
    "corpus_ingested": CorpusIngested,
    "document_retrieved": DocumentRetrieved,
    "entity_referenced": EntityReferenced,
    "schema_discovered": SchemaDiscovered,
    "search_failed": SearchFailed,
    "fact_disputed": FactDisputed,
    "contextual_insight_discovered": ContextualInsightDiscovered,
    "boundary_identified": BoundaryIdentified,
    "constant_documented": ConstantDocumented,
    "result_recorded": ResultRecorded,
    "architecture_invariant_observed": ArchitectureInvariantObserved,
    "map_entry_inserted": MapEntryInserted,
    "map_entry_promoted": MapEntryPromoted,  # deprecated — kept for historical deserialization
    "map_entry_evicted": MapEntryEvicted,
    "map_entry_referenced": MapEntryReferenced,
}

# Backward-compatibility alias (used by deserialize_event internally)
EVENT_REGISTRY = CONTEXT_MAP_EVENT_REGISTRY


def deserialize_event(data: dict[str, Any]) -> ContextMapEvent:
    event_type = str(data.get("event_type", ""))
    cls = EVENT_REGISTRY.get(event_type, ContextMapEvent)
    return cls.model_validate(data)
