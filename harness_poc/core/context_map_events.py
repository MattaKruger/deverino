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


class MapEntryPromoted(ContextMapEvent):
    event_type: Literal["map_entry_promoted"] = "map_entry_promoted"
    entry_key: str
    from_section: str
    to_section: str


class MapEntryEvicted(ContextMapEvent):
    event_type: Literal["map_entry_evicted"] = "map_entry_evicted"
    entry_key: str
    section: str
    reason: str


EVENT_REGISTRY: dict[str, type[ContextMapEvent]] = {
    "corpus_ingested": CorpusIngested,
    "document_retrieved": DocumentRetrieved,
    "entity_referenced": EntityReferenced,
    "schema_discovered": SchemaDiscovered,
    "search_failed": SearchFailed,
    "fact_disputed": FactDisputed,
    "contextual_insight_discovered": ContextualInsightDiscovered,
    "map_entry_promoted": MapEntryPromoted,
    "map_entry_evicted": MapEntryEvicted,
}


def deserialize_event(data: dict[str, Any]) -> ContextMapEvent:
    event_type = str(data.get("event_type", ""))
    cls = EVENT_REGISTRY.get(event_type, ContextMapEvent)
    return cls.model_validate(data)
