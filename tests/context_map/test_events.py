from __future__ import annotations

from harness_poc.core.events.context_map_events import (
    CONTEXT_MAP_EVENT_REGISTRY,
    MapEntryEvicted,
    MapEntryReferenced,
    deserialize_event,
)


def test_map_entry_referenced_round_trip() -> None:
    event = MapEntryReferenced(
        session_id="s1",
        corpus_key="codebase",
        entry_id="e-1",
        entry_key="codebase-entry-point",
        section="context_understanding",
        cycle_n=4,
        citation_context="...cited at app_factory.py:42...",
    )
    dumped = event.model_dump()
    assert dumped["event_type"] == "map_entry_referenced"
    revived = deserialize_event(dumped)
    assert isinstance(revived, MapEntryReferenced)
    assert revived.entry_key == "codebase-entry-point"
    assert revived.cycle_n == 4


def test_map_entry_referenced_in_registry() -> None:
    assert CONTEXT_MAP_EVENT_REGISTRY["map_entry_referenced"] is MapEntryReferenced


def test_map_entry_evicted_carries_materialization_count() -> None:
    event = MapEntryEvicted(
        session_id="s1",
        corpus_key="codebase",
        entry_key="stale-key",
        section="context_understanding",
        reason="stale@cycle=10,age=8,type=entity",
        materialization_count=2,
    )
    dumped = event.model_dump()
    assert dumped["materialization_count"] == 2
    assert dumped["reason"] == "stale@cycle=10,age=8,type=entity"


def test_map_entry_evicted_defaults_materialization_count_to_zero() -> None:
    event = MapEntryEvicted(
        session_id="s1",
        corpus_key="codebase",
        entry_key="k",
        section="domain_constants",
        reason="budget@cycle=1,priority=0.400",
    )
    assert event.materialization_count == 0
