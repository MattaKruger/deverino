from __future__ import annotations

from harness_poc.core.context_map.cartographer import deterministic_cartographer
from harness_poc.core.context_map.config import CartographerConfig
from harness_poc.core.context_map.schema import DistillerEntry

_SCORED = [
    "dispute", "schema", "insight", "architecture",
    "boundary", "entity", "result", "constant",
]


def _entry(key: str, obs_type: str = "entity", summary: str = "s") -> DistillerEntry:
    return DistillerEntry(
        key=key,
        observation_type=obs_type,  # type: ignore[arg-type]
        summary=summary,
        source_event_ids=[f"ev-{key}"],
    )


def _config(**overrides: object) -> CartographerConfig:
    """Build a CartographerConfig with sensible test defaults.

    Convenience: if a scalar float is passed for staleness_penalty,
    staleness_floor, recency_bonus, or recency_cap, it is broadcast
    to all scored types.  Dict overrides are passed through as-is.
    """
    # Build per-type dicts from scalar defaults, then apply overrides.
    raw: dict[str, object] = {
        "token_budget": 10_000,
        "recency_bonus": 0.0,  # disable for clarity
        "recency_cap": 0.0,
        "staleness_penalty": 0.1,
        "staleness_floor": 0.2,
    }
    raw.update(overrides)
    # Broadcast any scalar values to per-type dicts
    for key in ("recency_bonus", "recency_cap", "staleness_penalty", "staleness_floor"):
        val = raw[key]
        if isinstance(val, (int, float)):
            raw[key] = {t: float(val) for t in _SCORED}
    return CartographerConfig(**raw)  # type: ignore[arg-type]


def test_entry_below_staleness_floor_is_evicted() -> None:
    seed = deterministic_cartographer(
        distilled=[_entry("k", "constant")],  # base 0.4
        current_map=[],
        cycle_n=0,
        config=_config(),
    )
    # After 3 missed cycles: 0.4 - 3 * 0.1 = 0.1 < 0.2 → evict
    result = deterministic_cartographer(
        distilled=[],
        current_map=seed.new_map,
        cycle_n=3,
        config=_config(),
    )
    assert result.new_map == []
    assert len(result.evictions) == 1
    eviction = result.evictions[0]
    assert eviction.key == "k"
    assert eviction.observation_type == "constant"
    assert eviction.reason == "stale@cycle=3,age=3,type=constant"


def test_entry_above_staleness_floor_survives() -> None:
    seed = deterministic_cartographer(
        distilled=[_entry("k", "dispute")],  # base 1.0
        current_map=[],
        cycle_n=0,
        config=_config(),
    )
    # After 3 missed cycles: 1.0 - 3 * 0.1 = 0.7 > 0.2 → survive
    result = deterministic_cartographer(
        distilled=[],
        current_map=seed.new_map,
        cycle_n=3,
        config=_config(),
    )
    assert len(result.new_map) == 1
    assert result.evictions == []


def test_budget_eviction_trims_lowest_priority_tail() -> None:
    # Two entries in different sections, tight budget.
    # With section reservations, both entries need to share a single
    # section to reproduce the old flat-budget behavior.  We assign
    # all budget to context_roadmap where dispute lives.
    distilled = [
        DistillerEntry(
            key="keeps",
            observation_type="dispute",  # base 1.0, section=context_roadmap
            summary="kept summary",
            source_event_ids=["ev-a"],
        ),
        DistillerEntry(
            key="drops",
            observation_type="insight",  # base 0.8, section=context_roadmap
            summary="dropped summary",
            source_event_ids=["ev-b"],
        ),
    ]
    config = CartographerConfig(
        token_budget=3,  # one short summary fits, not both
        recency_bonus=dict.fromkeys(_SCORED, 0.0),
        recency_cap=dict.fromkeys(_SCORED, 0.0),
        staleness_penalty=dict.fromkeys(_SCORED, 0.0),
        staleness_floor=dict.fromkeys(_SCORED, 0.0),
        section_budget_share={
            "context_roadmap": 1.0,
            "parsing_schema": 0.0,
            "context_architecture": 0.0,
            "context_understanding": 0.0,
            "domain_constants": 0.0,
            "reusable_results": 0.0,
        },
    )
    result = deterministic_cartographer(
        distilled=distilled,
        current_map=[],
        cycle_n=0,
        config=config,
    )
    survivor_keys = [e.key for e in result.new_map]
    assert survivor_keys == ["keeps"]
    assert len(result.evictions) == 1
    eviction = result.evictions[0]
    assert eviction.key == "drops"
    assert eviction.reason.startswith("budget@cycle=0,priority=")


def test_budget_eviction_tie_breaks_deterministically() -> None:
    # Three entity entries (all context_understanding), only 2 tokens budget.
    # Assign all budget to context_understanding for analogous behavior.
    distilled = [
        DistillerEntry(
            key=f"k{i}",
            observation_type="entity",
            summary="x",
            source_event_ids=[f"ev-{i}"],
        )
        for i in range(3)
    ]
    config = CartographerConfig(
        token_budget=2,  # only ~2 tokens worth survive
        recency_bonus=dict.fromkeys(_SCORED, 0.0),
        recency_cap=dict.fromkeys(_SCORED, 0.0),
        staleness_penalty=dict.fromkeys(_SCORED, 0.0),
        staleness_floor=dict.fromkeys(_SCORED, 0.0),
        section_budget_share={
            "context_understanding": 1.0,
            "parsing_schema": 0.0,
            "context_architecture": 0.0,
            "context_roadmap": 0.0,
            "domain_constants": 0.0,
            "reusable_results": 0.0,
        },
    )
    seed = deterministic_cartographer(
        distilled=distilled,
        current_map=[],
        cycle_n=0,
        config=CartographerConfig(
            token_budget=10_000,
            recency_bonus=dict.fromkeys(_SCORED, 0.0),
            recency_cap=dict.fromkeys(_SCORED, 0.0),
            staleness_penalty=dict.fromkeys(_SCORED, 0.0),
            staleness_floor=dict.fromkeys(_SCORED, 0.0),
        ),  # no eviction
    )
    again_a = deterministic_cartographer(
        distilled=[],
        current_map=seed.new_map,
        cycle_n=1,
        config=config,
    )
    again_b = deterministic_cartographer(
        distilled=[],
        current_map=seed.new_map,
        cycle_n=1,
        config=config,
    )
    assert [e.entry_id for e in again_a.new_map] == [e.entry_id for e in again_b.new_map]
    assert [e.entry_id for e in again_a.evictions] == [e.entry_id for e in again_b.evictions]
