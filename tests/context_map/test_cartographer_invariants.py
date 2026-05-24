from __future__ import annotations

from datetime import UTC, datetime

from harness_poc.core.context_map.cartographer import deterministic_cartographer
from harness_poc.core.context_map.config import CartographerConfig
from harness_poc.core.context_map.schema import DistillerEntry

_TYPES = ("entity", "schema", "insight", "dispute", "boundary", "constant", "result", "architecture")


def _distilled(n: int) -> list[DistillerEntry]:
    return [
        DistillerEntry(
            key=f"k{i}",
            observation_type=_TYPES[i % len(_TYPES)],  # type: ignore[arg-type]
            summary=f"sum {i} " * (i % 5 + 1),
            source_event_ids=[f"ev-{i}"],
        )
        for i in range(n)
    ]


def test_invariant_budget_never_exceeded() -> None:
    config = CartographerConfig(token_budget=40)
    result = deterministic_cartographer(
        distilled=_distilled(20),
        current_map=[],
        cycle_n=0,
        config=config,
    )
    total = sum(e.token_estimate for e in result.new_map)
    assert total <= config.token_budget


def _broadcast_scalar(value: float) -> dict[str, float]:
    """Broadcast a scalar to all scored observation types for per-type dicts."""
    scored = [
        "dispute", "schema", "insight", "architecture",
        "boundary", "entity", "result", "constant",
    ]
    return {t: value for t in scored}


def test_invariant_no_survivor_below_staleness_floor() -> None:
    config = CartographerConfig(
        token_budget=10_000,
        recency_bonus=_broadcast_scalar(0.0),
        recency_cap=_broadcast_scalar(0.0),
        staleness_penalty=_broadcast_scalar(0.5),
        staleness_floor=_broadcast_scalar(0.5),
    )
    seed = deterministic_cartographer(
        distilled=_distilled(7),
        current_map=[],
        cycle_n=0,
        config=config,
    )
    result = deterministic_cartographer(
        distilled=[],
        current_map=seed.new_map,
        cycle_n=10,
        config=config,
    )
    for entry in result.new_map:
        assert entry.priority >= config.staleness_floor[entry.observation_type]


def test_invariant_every_eviction_corresponds_to_known_entry() -> None:
    config = CartographerConfig(token_budget=20)
    distilled = _distilled(12)
    result = deterministic_cartographer(
        distilled=distilled,
        current_map=[],
        cycle_n=0,
        config=config,
    )
    known_keys = {d.key for d in distilled}
    for eviction in result.evictions:
        assert eviction.key in known_keys


def test_invariant_entry_id_stable_across_cycles_for_survivors() -> None:
    fixed_now = datetime(2026, 5, 23, tzinfo=UTC)
    config = CartographerConfig(token_budget=10_000)
    distilled = _distilled(5)
    a = deterministic_cartographer(
        distilled=distilled,
        current_map=[],
        cycle_n=0,
        config=config,
        now=fixed_now,
    )
    b = deterministic_cartographer(
        distilled=distilled,
        current_map=a.new_map,
        cycle_n=1,
        config=config,
        now=fixed_now,
    )
    a_ids = {(e.key, e.entry_id) for e in a.new_map}
    b_ids = {(e.key, e.entry_id) for e in b.new_map}
    assert a_ids == b_ids
