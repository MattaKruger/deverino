from __future__ import annotations

from harness_poc.core.context_map.cartographer import deterministic_cartographer
from harness_poc.core.context_map.config import CartographerConfig
from harness_poc.core.context_map.schema import DistillerEntry


def _entry(
    key: str,
    obs_type: str = "entity",
    summary: str = "s",
    ids: tuple[str, ...] = ("ev-1",),
) -> DistillerEntry:
    return DistillerEntry(
        key=key,
        observation_type=obs_type,  # type: ignore[arg-type]
        summary=summary,
        source_event_ids=list(ids),
    )


def _config() -> CartographerConfig:
    # Use a huge budget so dedup tests are not affected by eviction.
    return CartographerConfig(token_budget=10_000)


def test_new_key_inserts_fresh_map_entry() -> None:
    distilled = [_entry("k1")]
    result = deterministic_cartographer(
        distilled=distilled,
        current_map=[],
        cycle_n=1,
        config=_config(),
    )
    assert len(result.new_map) == 1
    entry = result.new_map[0]
    assert entry.key == "k1"
    assert entry.materialization_count == 1
    assert entry.first_seen_cycle == 1
    assert entry.last_seen_cycle == 1
    assert entry.entry_id  # non-empty UUID


def test_existing_key_with_newer_events_replaces_summary_and_keeps_entry_id() -> None:
    seed = deterministic_cartographer(
        distilled=[_entry("k1", summary="old", ids=("ev-1",))],
        current_map=[],
        cycle_n=1,
        config=_config(),
    )
    original = seed.new_map[0]

    result = deterministic_cartographer(
        distilled=[_entry("k1", summary="new", ids=("ev-1", "ev-2"))],
        current_map=seed.new_map,
        cycle_n=2,
        config=_config(),
    )
    updated = next(e for e in result.new_map if e.key == "k1")
    assert updated.entry_id == original.entry_id  # stable
    assert updated.first_seen == original.first_seen  # stable
    assert updated.summary == "new"
    assert updated.source_event_ids == ["ev-1", "ev-2"]
    assert updated.materialization_count == 2
    assert updated.last_seen_cycle == 2


def test_existing_key_with_subset_events_is_noop_but_credits_survival() -> None:
    seed = deterministic_cartographer(
        distilled=[_entry("k1", summary="orig", ids=("ev-1", "ev-2"))],
        current_map=[],
        cycle_n=1,
        config=_config(),
    )

    result = deterministic_cartographer(
        distilled=[_entry("k1", summary="should-not-overwrite", ids=("ev-1",))],
        current_map=seed.new_map,
        cycle_n=2,
        config=_config(),
    )
    updated = next(e for e in result.new_map if e.key == "k1")
    assert updated.summary == "orig"  # unchanged
    assert updated.source_event_ids == ["ev-1", "ev-2"]  # unchanged
    assert updated.materialization_count == 2  # credited
    assert updated.last_seen_cycle == 2


def test_missing_distilled_entries_keep_existing_map_entries() -> None:
    seed = deterministic_cartographer(
        distilled=[_entry("k1"), _entry("k2")],
        current_map=[],
        cycle_n=1,
        config=_config(),
    )

    result = deterministic_cartographer(
        distilled=[_entry("k1")],
        current_map=seed.new_map,
        cycle_n=2,
        config=_config(),
    )
    keys = {e.key for e in result.new_map}
    assert keys == {"k1", "k2"}  # k2 carried forward
    k2 = next(e for e in result.new_map if e.key == "k2")
    assert k2.last_seen_cycle == 1  # not bumped — wasn't in this cycle's distilled
