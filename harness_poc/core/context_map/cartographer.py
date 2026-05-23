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
    """Run dedup → priority → staleness → budget. Pure function.

    Pure: identical (distilled, current_map, cycle_n, config) → identical result,
    given identical now (or a stable clock supplied by the caller).
    """
    timestamp = now or datetime.now(tz=UTC)
    working = _dedup_and_merge(distilled, current_map, cycle_n, config, timestamp)
    working = [_apply_priority(e, cycle_n, config) for e in working]
    working, stale_evictions = _evict_stale(working, cycle_n, config)
    working, budget_evictions = _enforce_budget(working, cycle_n, config)
    return CartographerResult(
        new_map=working,
        evictions=[*stale_evictions, *budget_evictions],
        cycle_n=cycle_n,
    )


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
    raw_recency = age * config.recency_bonus
    recency = min(raw_recency, config.recency_cap)
    missed = max(0, cycle_n - entry.last_seen_cycle)
    penalty = missed * config.staleness_penalty
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
        if entry.priority < config.staleness_floor:
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
    # Sort desc by priority, then desc by last_updated, then asc by entry_id.
    ordered = sorted(
        entries,
        key=lambda e: (-e.priority, -e.last_updated.timestamp(), e.entry_id),
    )
    survivors: list[MapEntry] = []
    evicted: list[EvictionRecord] = []
    used = 0
    for entry in ordered:
        if used + entry.token_estimate <= config.token_budget:
            survivors.append(entry)
            used += entry.token_estimate
        else:
            evicted.append(
                EvictionRecord(
                    entry_id=entry.entry_id,
                    key=entry.key,
                    section=entry.section,
                    observation_type=entry.observation_type,
                    materialization_count=entry.materialization_count,
                    reason=f"budget@cycle={cycle_n},priority={entry.priority:.3f}",
                )
            )
    return survivors, evicted
