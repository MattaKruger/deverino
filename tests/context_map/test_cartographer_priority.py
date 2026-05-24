from __future__ import annotations

import pytest

from harness_poc.core.context_map.cartographer import deterministic_cartographer
from harness_poc.core.context_map.config import CartographerConfig
from harness_poc.core.context_map.schema import DistillerEntry

_SCORED = [
    "dispute", "schema", "insight", "architecture",
    "boundary", "entity", "result", "constant",
]


def _entry(key: str, obs_type: str) -> DistillerEntry:
    return DistillerEntry(
        key=key,
        observation_type=obs_type,  # type: ignore[arg-type]
        summary="summary text",
        source_event_ids=[f"ev-{key}"],
    )


def _config(**overrides: object) -> CartographerConfig:
    """Build a CartographerConfig with sensible test defaults.

    Convenience: scalar floats for decay params are broadcast to all scored types.
    """
    raw: dict[str, object] = {
        "token_budget": 10_000,
        "recency_bonus": 0.01,
        "recency_cap": 0.5,
        "staleness_penalty": 0.05,
        "staleness_floor": 0.0,  # disable eviction in priority-only tests
    }
    raw.update(overrides)
    for key in ("recency_bonus", "recency_cap", "staleness_penalty", "staleness_floor"):
        val = raw[key]
        if isinstance(val, (int, float)):
            raw[key] = {t: float(val) for t in _SCORED}
    return CartographerConfig(**raw)  # type: ignore[arg-type]


def test_priority_for_fresh_entry_equals_base_weight() -> None:
    result = deterministic_cartographer(
        distilled=[_entry("k", "entity")],
        current_map=[],
        cycle_n=0,
        config=_config(),
    )
    assert result.new_map[0].priority == pytest.approx(0.6)


def test_priority_uses_per_type_weights() -> None:
    result = deterministic_cartographer(
        distilled=[_entry("k", "dispute")],
        current_map=[],
        cycle_n=0,
        config=_config(),
    )
    assert result.new_map[0].priority == pytest.approx(1.0)


def test_recency_bonus_accumulates_with_age() -> None:
    seed = deterministic_cartographer(
        distilled=[_entry("k", "entity")],
        current_map=[],
        cycle_n=0,
        config=_config(),
    )
    result = deterministic_cartographer(
        distilled=[_entry("k", "entity")],
        current_map=seed.new_map,
        cycle_n=10,
        config=_config(),
    )
    # base 0.6 + (10 - 0) * 0.01 = 0.70
    assert result.new_map[0].priority == pytest.approx(0.70)


def test_recency_bonus_is_capped() -> None:
    seed = deterministic_cartographer(
        distilled=[_entry("k", "entity")],
        current_map=[],
        cycle_n=0,
        config=_config(recency_cap=0.05),
    )
    result = deterministic_cartographer(
        distilled=[_entry("k", "entity")],
        current_map=seed.new_map,
        cycle_n=100,
        config=_config(recency_cap=0.05),
    )
    # base 0.6 + min(0.05, 100 * 0.01) = 0.65
    assert result.new_map[0].priority == pytest.approx(0.65)


def test_staleness_penalty_reduces_priority_for_missed_cycles() -> None:
    seed = deterministic_cartographer(
        distilled=[_entry("k", "entity")],
        current_map=[],
        cycle_n=0,
        config=_config(),
    )
    result = deterministic_cartographer(
        distilled=[],  # k is not refreshed this cycle
        current_map=seed.new_map,
        cycle_n=4,
        config=_config(),
    )
    # base 0.6 + (4-0)*0.01 - (4-0)*0.05 = 0.6 + 0.04 - 0.20 = 0.44
    assert result.new_map[0].priority == pytest.approx(0.44)
