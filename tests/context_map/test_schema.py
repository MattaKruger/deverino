from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from harness_poc.core.context_map.schema import (
    CartographerResult,
    DistilledBatch,
    DistillerEntry,
    EvictionRecord,
    MapEntry,
)


def _now() -> datetime:
    return datetime(2026, 5, 23, tzinfo=UTC)


def test_distiller_entry_round_trip() -> None:
    entry = DistillerEntry(
        key="codebase-entry-point",
        observation_type="entity",
        summary="The repl is the primary entry point.",
        source_event_ids=["ev-1"],
        tags=["novel"],
    )
    dumped = entry.model_dump()
    revived = DistillerEntry.model_validate(dumped)
    assert revived == entry


def test_distiller_entry_requires_at_least_one_source_event() -> None:
    with pytest.raises(ValidationError):
        DistillerEntry(
            key="k",
            observation_type="entity",
            summary="s",
            source_event_ids=[],
        )


def test_distiller_entry_forbids_section_field() -> None:
    with pytest.raises(ValidationError):
        DistillerEntry.model_validate(
            {
                "key": "k",
                "observation_type": "entity",
                "summary": "s",
                "source_event_ids": ["ev-1"],
                "section": "context_understanding",
            }
        )


def test_distiller_entry_forbids_priority_field() -> None:
    with pytest.raises(ValidationError):
        DistillerEntry.model_validate(
            {
                "key": "k",
                "observation_type": "entity",
                "summary": "s",
                "source_event_ids": ["ev-1"],
                "priority": 0.9,
            }
        )


def test_distiller_entry_rejects_unknown_observation_type() -> None:
    with pytest.raises(ValidationError):
        DistillerEntry.model_validate(
            {
                "key": "k",
                "observation_type": "mystery",
                "summary": "s",
                "source_event_ids": ["ev-1"],
            }
        )


def test_distilled_batch_round_trip() -> None:
    batch = DistilledBatch(
        entries=[
            DistillerEntry(
                key="k1",
                observation_type="schema",
                summary="s",
                source_event_ids=["ev-1"],
            )
        ]
    )
    revived = DistilledBatch.model_validate(batch.model_dump())
    assert revived == batch


def test_map_entry_round_trip() -> None:
    entry = MapEntry(
        entry_id="uuid-1",
        key="k",
        section="context_understanding",
        observation_type="entity",
        summary="s",
        priority=0.6,
        source_event_ids=["ev-1"],
        first_seen=_now(),
        last_updated=_now(),
        materialization_count=1,
        first_seen_cycle=0,
        last_seen_cycle=0,
        token_estimate=5,
    )
    revived = MapEntry.model_validate(entry.model_dump())
    assert revived == entry


def test_cartographer_result_holds_evictions() -> None:
    result = CartographerResult(
        new_map=[],
        evictions=[
            EvictionRecord(
                entry_id="uuid-2",
                key="old",
                section="context_understanding",
                observation_type="entity",
                materialization_count=3,
                reason="stale@cycle=5,age=8,type=entity",
            )
        ],
        cycle_n=5,
    )
    assert result.cycle_n == 5
    assert result.evictions[0].reason.startswith("stale@")
