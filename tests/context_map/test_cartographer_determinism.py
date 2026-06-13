from __future__ import annotations

from datetime import UTC, datetime

from harness_poc.core.context_map.cartographer import deterministic_cartographer
from harness_poc.core.context_map.config import CartographerConfig
from harness_poc.core.context_map.schema import DistillerEntry, MapEntry


def _entries() -> list[DistillerEntry]:
    return [
        DistillerEntry(
            key=f"k{i}",
            observation_type=t,  # type: ignore[arg-type]
            summary=f"summary {i} for type {t}",
            source_event_ids=[f"ev-{i}"],
        )
        for i, t in enumerate(
            ["entity", "schema", "insight", "dispute", "boundary", "constant", "result"]
        )
    ]


def _config() -> CartographerConfig:
    """Config with per-type values that avoid stochastic eviction/re-creation.

    The default per-type staleness_floor for constant (0.60) exceeds its
    base weight (0.40), causing constant entries to be evicted and
    re-created with new random UUIDs on every cycle — breaking determinism.
    We pin staleness_floor to 0.0 so no entries are evicted by staleness.
    """
    scored = [
        "dispute", "schema", "insight", "architecture",
        "boundary", "entity", "result", "constant",
    ]
    return CartographerConfig(
        token_budget=200,
        staleness_floor=dict.fromkeys(scored, 0.0),
    )


def _seed_map() -> tuple[list[MapEntry], datetime]:
    fixed_now = datetime(2026, 5, 23, tzinfo=UTC)
    seed = deterministic_cartographer(
        distilled=_entries(),
        current_map=[],
        cycle_n=0,
        config=_config(),
        now=fixed_now,
    )
    return seed.new_map, fixed_now


def test_identical_inputs_produce_identical_output_json() -> None:
    current_map, fixed_now = _seed_map()
    distilled = _entries()
    a = deterministic_cartographer(
        distilled=distilled,
        current_map=current_map,
        cycle_n=5,
        config=_config(),
        now=fixed_now,
    )
    b = deterministic_cartographer(
        distilled=distilled,
        current_map=current_map,
        cycle_n=5,
        config=_config(),
        now=fixed_now,
    )
    assert a.model_dump_json() == b.model_dump_json()


def test_repeated_invocation_stable_over_many_runs() -> None:
    current_map, fixed_now = _seed_map()
    distilled = _entries()
    outputs = {
        deterministic_cartographer(
            distilled=distilled,
            current_map=current_map,
            cycle_n=5,
            config=_config(),
            now=fixed_now,
        ).model_dump_json()
        for _ in range(20)
    }
    assert len(outputs) == 1
