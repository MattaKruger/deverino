"""Deterministic observation_type → section mapping (no LLM judgment)."""

from __future__ import annotations

SECTION_MAP: dict[str, str] = {
    "schema": "parsing_schema",
    "entity": "context_understanding",
    "boundary": "context_understanding",
    "insight": "context_roadmap",
    "dispute": "context_roadmap",
    "constant": "domain_constants",
    "result": "reusable_results",
}


def assign_section(observation_type: str) -> str:
    """Return the section name for a given observation_type.

    Raises KeyError with a descriptive message on unknown types.
    """
    try:
        return SECTION_MAP[observation_type]
    except KeyError as exc:
        msg = f"unknown observation_type: {observation_type!r}"
        raise KeyError(msg) from exc
