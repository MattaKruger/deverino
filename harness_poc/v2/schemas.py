"""V2 Pydantic schemas — Event and MaterializedContext per the planning spec.

These models bind the event ledger directly to the dynamic state
materialization pipeline defined in planning_specv2.md §4.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from uuid import UUID


class Event(BaseModel):
    """A single event in the context event stream.

    Maps to the ``context_events`` PostgreSQL table.
    """

    model_config = ConfigDict(extra="forbid")

    id: int | None = None
    session_id: UUID = Field(default_factory=uuid4)
    team_member: str
    event_type: str  # PROBE_FAILED | SPEC_COMMITTED | GATE_PASSED | CONTEXT_WARMED
    payload: dict[str, Any] = Field(default_factory=dict)


class MaterializedContext(BaseModel):
    """A materialized context map snapshot bound to a persona+pedagogy lens.

    Maps to the ``materialized_context_maps`` PostgreSQL table.
    """

    model_config = ConfigDict(extra="forbid")

    project_id: str
    active_persona: str
    pedagogy_snapshot: dict[str, Any] = Field(default_factory=dict)
    working_context_delta: dict[str, Any] = Field(default_factory=dict)
    verified_topology: dict[str, Any] = Field(default_factory=dict)
