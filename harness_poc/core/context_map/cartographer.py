"""Deterministic Cartographer — pure function, no I/O, no clock."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from functools import lru_cache

import tiktoken

from harness_poc.core.context_map.config import CartographerConfig
from harness_poc.core.context_map.schema import (
    CartographerResult,
    DistillerEntry,
    EvictionRecord,
    MapEntry,
)
from harness_poc.core.context_map.sections import assign_section


def deterministic_cartographer(
    distilled: Sequence[DistillerEntry],
    current_map: Sequence[MapEntry],
    cycle_n: int,
    config: CartographerConfig,
    *,
    now: datetime | None = None,
) -> CartographerResult:
    """Run stage-0 → dedup → priority → staleness → budget. Pure function.

    Pure: identical (distilled, current_map, cycle_n, config) → identical result,
    given identical now (or a stable clock supplied by the caller).
    """
    timestamp = now or datetime.now(tz=UTC)

    # Stage 0: process obsolete entries before dedup/merge
    distilled_no_obsoletes = [d for d in distilled if d.observation_type != "obsolete"]
    working, obsolete_evictions = _stage_0_explicit_removals(
        distilled, current_map, cycle_n
    )

    working = _dedup_and_merge(distilled_no_obsoletes, working, cycle_n, config, timestamp)
    working = [_apply_priority(e, cycle_n, config) for e in working]
    working, stale_evictions = _evict_stale(working, cycle_n, config)
    working, budget_evictions = _enforce_budget(working, cycle_n, config)
    return CartographerResult(
        new_map=working,
        evictions=[*obsolete_evictions, *stale_evictions, *budget_evictions],
        cycle_n=cycle_n,
    )


def _stage_0_explicit_removals(
    distilled: Sequence[DistillerEntry],
    current_map: Sequence[MapEntry],
    cycle_n: int,
) -> tuple[list[MapEntry], list[EvictionRecord]]:
    """Process obsolete entries before dedup/merge.

    Obsolete entries declare that an existing key is no longer true.
    Matching is by exact string equality on MapEntry.key — no fuzzy matching.
    A miss (key not found) is a silent no-op per spec §9.1 decision A.
    """
    obsolete_keys = {d.key for d in distilled if d.observation_type == "obsolete"}
    if not obsolete_keys:
        return list(current_map), []

    survivors: list[MapEntry] = []
    evictions: list[EvictionRecord] = []
    for entry in current_map:
        if entry.key in obsolete_keys:
            evictions.append(
                EvictionRecord(
                    entry_id=entry.entry_id,
                    key=entry.key,
                    section=entry.section,
                    observation_type=entry.observation_type,
                    materialization_count=entry.materialization_count,
                    reason=f"obsolete@cycle={cycle_n}",
                )
            )
        else:
            survivors.append(entry)
    return survivors, evictions


def _dedup_and_merge(
    distilled: Sequence[DistillerEntry],
    current_map: Sequence[MapEntry],
    cycle_n: int,
    config: CartographerConfig,
    now: datetime,
) -> list[MapEntry]:
    by_key: dict[str, MapEntry] = {e.key: e for e in current_map}

    for d in distilled:
        existing = by_key.get(d.key)
        if existing is None:
            by_key[d.key] = _new_map_entry(d, cycle_n, config, now)
            continue

        if _is_strict_superset(d.source_event_ids, existing.source_event_ids):
            by_key[d.key] = existing.model_copy(
                update={
                    "summary": d.summary,
                    "source_event_ids": list(d.source_event_ids),
                    "last_updated": now,
                    "materialization_count": existing.materialization_count + 1,
                    "last_seen_cycle": cycle_n,
                    "token_estimate": _estimate_tokens(d.summary, config.tokenizer_name),
                }
            )
        else:
            by_key[d.key] = existing.model_copy(
                update={
                    "materialization_count": existing.materialization_count + 1,
                    "last_seen_cycle": cycle_n,
                }
            )

    return list(by_key.values())


def _new_map_entry(
    d: DistillerEntry,
    cycle_n: int,
    config: CartographerConfig,
    now: datetime,
) -> MapEntry:
    base_priority = config.priority_weights[d.observation_type]
    return MapEntry(
        entry_id=str(uuid.uuid4()),
        key=d.key,
        section=assign_section(d.observation_type),
        observation_type=d.observation_type,
        summary=d.summary,
        priority=base_priority,
        source_event_ids=list(d.source_event_ids),
        first_seen=now,
        last_updated=now,
        materialization_count=1,
        first_seen_cycle=cycle_n,
        last_seen_cycle=cycle_n,
        token_estimate=_estimate_tokens(d.summary, config.tokenizer_name),
    )


def _is_strict_superset(new_ids: Sequence[str], existing_ids: Sequence[str]) -> bool:
    new_set, existing_set = set(new_ids), set(existing_ids)
    return new_set != existing_set and existing_set.issubset(new_set)


@lru_cache(maxsize=4)
def _get_encoder(tokenizer_name: str) -> tiktoken.Encoding:
    return tiktoken.get_encoding(tokenizer_name)


def _estimate_tokens(text: str, tokenizer_name: str) -> int:
    return len(_get_encoder(tokenizer_name).encode(text))


def _apply_priority(
    entry: MapEntry,
    cycle_n: int,
    config: CartographerConfig,
) -> MapEntry:
    base = config.priority_weights[entry.observation_type]
    age = max(0, cycle_n - entry.first_seen_cycle)
    raw_recency = age * config.recency_bonus[entry.observation_type]
    recency = min(raw_recency, config.recency_cap[entry.observation_type])
    missed = max(0, cycle_n - entry.last_seen_cycle)
    penalty = missed * config.staleness_penalty[entry.observation_type]
    priority = base + recency - penalty
    return entry.model_copy(update={"priority": priority})


def _evict_stale(
    entries: Sequence[MapEntry],
    cycle_n: int,
    config: CartographerConfig,
) -> tuple[list[MapEntry], list[EvictionRecord]]:
    survivors: list[MapEntry] = []
    evictions: list[EvictionRecord] = []
    for entry in entries:
        if entry.priority < config.staleness_floor[entry.observation_type]:
            age = cycle_n - entry.last_seen_cycle
            evictions.append(
                EvictionRecord(
                    entry_id=entry.entry_id,
                    key=entry.key,
                    section=entry.section,
                    observation_type=entry.observation_type,
                    materialization_count=entry.materialization_count,
                    reason=f"stale@cycle={cycle_n},age={age},type={entry.observation_type}",
                )
            )
        else:
            survivors.append(entry)
    return survivors, evictions


def _enforce_budget(
    entries: Sequence[MapEntry],
    cycle_n: int,
    config: CartographerConfig,
) -> tuple[list[MapEntry], list[EvictionRecord]]:
    """Two-pass budget enforcement with per-section reservations.

    Pass 1: each section fills its reserved share (by priority).
    Pass 2: remaining budget allocated across all sections by global priority.

    Edge cases per spec §5:
    - Unfilled share flows to the global pool (Pass 2).
    - Entries evicted in Pass 1 are NOT rescued in Pass 2 (§5.4.1).
    - A single entry exceeding its section's share is evicted (§5.4.1).
    """
    # Group by section
    by_section: dict[str, list[MapEntry]] = {}
    for e in entries:
        by_section.setdefault(e.section, []).append(e)

    # Sort each section by priority desc, then last_updated desc, then entry_id asc
    for section_entries in by_section.values():
        section_entries.sort(
            key=lambda e: (-e.priority, -e.last_updated.timestamp(), e.entry_id)
        )

    survivors: list[MapEntry] = []
    evictions: list[EvictionRecord] = []
    remaining_budget = config.token_budget

    # Pass 1: fill each section's reserved share
    for section, share in config.section_budget_share.items():
        section_budget = int(config.token_budget * share)
        section_entries = by_section.pop(section, [])
        used = 0
        for entry in section_entries:
            if used + entry.token_estimate <= section_budget:
                survivors.append(entry)
                used += entry.token_estimate
            else:
                evictions.append(
                    EvictionRecord(
                        entry_id=entry.entry_id,
                        key=entry.key,
                        section=entry.section,
                        observation_type=entry.observation_type,
                        materialization_count=entry.materialization_count,
                        reason=(
                            f"budget@cycle={cycle_n},"
                            f"priority={entry.priority:.3f},"
                            f"section={section}"
                        ),
                    )
                )
        remaining_budget -= used

    # Pass 2: fill remaining budget from all sections by global priority
    all_remaining: list[MapEntry] = []
    for section_entries in by_section.values():
        all_remaining.extend(section_entries)
    all_remaining.sort(
        key=lambda e: (-e.priority, -e.last_updated.timestamp(), e.entry_id)
    )

    for entry in all_remaining:
        if remaining_budget <= 0:
            evictions.append(
                EvictionRecord(
                    entry_id=entry.entry_id,
                    key=entry.key,
                    section=entry.section,
                    observation_type=entry.observation_type,
                    materialization_count=entry.materialization_count,
                    reason=f"budget@cycle={cycle_n},priority={entry.priority:.3f}",
                )
            )
            continue
        if entry.token_estimate <= remaining_budget:
            survivors.append(entry)
            remaining_budget -= entry.token_estimate
        else:
            evictions.append(
                EvictionRecord(
                    entry_id=entry.entry_id,
                    key=entry.key,
                    section=entry.section,
                    observation_type=entry.observation_type,
                    materialization_count=entry.materialization_count,
                    reason=f"budget@cycle={cycle_n},priority={entry.priority:.3f}",
                )
            )

    return survivors, evictions
