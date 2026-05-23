from __future__ import annotations

import pytest
from pydantic_ai.models.test import TestModel

from harness_poc.core.context_map.config import DistillerConfig
from harness_poc.core.context_map.distiller import run_distiller
from harness_poc.core.context_map.schema import DistilledBatch, DistillerEntry
from harness_poc.core.events.context_map_events import EntityReferenced

pytestmark = pytest.mark.asyncio


def _event(event_id: str) -> EntityReferenced:
    return EntityReferenced(
        event_id=event_id,
        session_id="s",
        corpus_key="codebase",
        entity_name="SkillRunner",
        entity_type="class",
        context="dispatches skills",
    )


async def test_valid_distiller_output_returned() -> None:
    valid_batch = DistilledBatch(
        entries=[
            DistillerEntry(
                key="skill-runner",
                observation_type="entity",
                summary="SkillRunner dispatches skills",
                source_event_ids=["ev-1"],
            )
        ]
    )
    model = TestModel(custom_output_args=valid_batch.model_dump())
    result = await run_distiller(
        events=[_event("ev-1")],
        model=model,
        config=DistillerConfig(),
    )
    assert len(result) == 1
    assert result[0].key == "skill-runner"


async def test_unknown_source_event_id_triggers_retry_then_fallback() -> None:
    bad_batch = DistilledBatch(
        entries=[
            DistillerEntry(
                key="ghost",
                observation_type="entity",
                summary="cites a non-existent event",
                source_event_ids=["ev-does-not-exist"],
            )
        ]
    )
    model = TestModel(custom_output_args=bad_batch.model_dump())
    result = await run_distiller(
        events=[_event("ev-1")],
        model=model,
        config=DistillerConfig(max_retries=2),
    )
    assert result == []  # safe fallback


async def test_zero_entries_is_valid() -> None:
    empty = DistilledBatch(entries=[])
    model = TestModel(custom_output_args=empty.model_dump())
    result = await run_distiller(
        events=[_event("ev-1")],
        model=model,
        config=DistillerConfig(),
    )
    assert result == []
