"""Pydantic schemas for the Distiller → Cartographer pipeline."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ObservationType = Literal[
    "entity",
    "schema",
    "insight",
    "dispute",
    "boundary",
    "constant",
    "result",
]
Tag = Literal["confirmed", "novel", "correcting"]


class DistillerEntry(BaseModel):
    """A single observation emitted by the Distiller LLM call."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str = Field(..., description="Stable slug, e.g. 'codebase-entry-point'")
    observation_type: ObservationType
    summary: str = Field(..., description="One-paragraph orientation fact")
    source_event_ids: list[str] = Field(..., min_length=1)
    tags: list[Tag] = Field(default_factory=list)


class DistilledBatch(BaseModel):
    """Top-level output_type passed to the Distiller agent."""

    model_config = ConfigDict(extra="forbid")

    entries: list[DistillerEntry]


class MapEntry(BaseModel):
    """A materialized context-map row."""

    model_config = ConfigDict(extra="forbid")

    entry_id: str
    key: str
    section: str
    observation_type: ObservationType
    summary: str
    priority: float
    source_event_ids: list[str]
    first_seen: datetime
    last_updated: datetime
    materialization_count: int = 0
    first_seen_cycle: int
    last_seen_cycle: int
    token_estimate: int


class EvictionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    entry_id: str
    key: str
    section: str
    observation_type: ObservationType
    materialization_count: int
    reason: str  # Structured: see schema doc


class CartographerResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    new_map: list[MapEntry]
    evictions: list[EvictionRecord]
    cycle_n: int
