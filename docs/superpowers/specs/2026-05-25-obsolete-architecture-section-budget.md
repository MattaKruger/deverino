# Obsolete, Architecture, and Section Budget — Design

**Date:** 2026-05-25
**Status:** Draft — open questions resolved; ready for implementation
**Depends on:** `docs/superpowers/specs/2026-05-23-deterministic-cartographer-design.md` (Part 1), `docs/superpowers/specs/2026-05-24-deterministic-cartographer-deferred-features.md` (Part 2)

## 1. Purpose & Scope

Four changes to the context-map pipeline that shift it from "mostly-deterministic priority scoring" toward "type-aware lifecycle management":

1. **`obsolete` observation type** — the agent can explicitly declare that a map entry is no longer true, removing it by key.
2. **Per-type decay configuration** — staleness and recency parameters become type-specific instead of global.
3. **`architecture` observation type** — a new type for cross-cutting structural invariants, distinct from entity/insight.
4. **Section budget reservations** — each section gets a guaranteed share of the token budget, preventing any one section from crowding out structurally important knowledge.

All four are pure extensions to the deterministic Cartographer. The Distiller gains one new observation type (`architecture`) and one new output type (`obsolete`). The Cartographer gains a `stage_0_explicit_removals` pass and a budget-reservation pass. The configuration surface expands but the core algorithm remains: dedup → priority → staleness → budget.

### In scope

- `Obsolete` observation type: Distiller prompt update, schema change, Cartographer key-removal pass.
- Per-type decay: restructuring `CartographerConfig` so `staleness_penalty`, `staleness_floor`, `recency_bonus`, `recency_cap` become `dict[str, float]` keyed by observation type.
- `Architecture` observation type: Distiller prompt update, schema change, section assignment to new `context_architecture` section, `observe` tool prompt update, `ContextMapArchitectureObserved` event.
- Section budget reservations: config surface, `_enforce_budget` rewrite with per-section allocation pass.
- Configuration surface: complete `harness.yaml` fragment for all new keys.
- Calibration impact analysis.
- Migration plan.

### Out of scope

- Changing the Cartographer's pure-function contract or the four-stage pipeline shape.
- `obsolete` events triggered automatically by the Evictor (the Evictor continues to emit `MapEntryEvicted` with `reason=stale@...` or `reason=budget@...`; `obsolete` is agent-initiated only).
- Per-type `recency_bonus` affecting the calibration formula (calibration currently tunes only `priority_weights`; per-type decay params are static config).
- Automatic reclassification of existing entries from `entity` → `architecture`.

---

## 2. Change 1 — `obsolete` observation type

### 2.1 Rationale

Today, the only way an entry leaves the map is through the Evictor: staleness decay below the floor, or budget pressure. Both are implicit — the agent never says "this fact is wrong." The `dispute` type covers corrections (replace a claim with a corrected version), but there is no way to say "this entry was true once and is now simply false — remove it."

`obsolete` fills that gap. It is an explicit, agent-initiated removal by key. The Cartographer processes it before dedup/merge so that an `obsolete` entry and a replacement entry with the same key in the same cycle don't race.

### 2.2 Distiller contract

The Distiller can emit entries with `observation_type: "obsolete"`. An `obsolete` entry has:

- `key` — the stable slug of the entry to remove (must match an existing key).
- `summary` — human-readable reason (e.g. "API endpoint /api/v1/search was removed in commit abc123").
- `source_event_ids` — the events that prove obsolescence.
- `tags` — typically `["correcting"]`.

**Key matching is explicit and exact.** The Cartographer checks `obsolete_keys` against the current map by direct string equality on `MapEntry.key`. No fuzzy matching, no partial prefix — this is deterministic and auditable. If the key is not found in the current map, the operation is a no-op (the entry was already evicted or never existed).

### 2.3 Cartographer processing

A new stage 0 pass runs before `_dedup_and_merge`:

```python
def _stage_0_explicit_removals(
    distilled: Sequence[DistillerEntry],
    current_map: Sequence[MapEntry],
    cycle_n: int,
) -> tuple[list[MapEntry], list[EvictionRecord]]:
    """Process obsolete entries before dedup/merge."""
    obsolete_keys = {d.key for d in distilled if d.observation_type == "obsolete"}
    if not obsolete_keys:
        return list(current_map), []

    survivors: list[MapEntry] = []
    evictions: list[EvictionRecord] = []
    for entry in current_map:
        if entry.key in obsolete_keys:
            evictions.append(EvictionRecord(
                entry_id=entry.entry_id,
                key=entry.key,
                section=entry.section,
                observation_type=entry.observation_type,
                materialization_count=entry.materialization_count,
                reason=f"obsolete@cycle={cycle_n}",
            ))
        else:
            survivors.append(entry)
    return survivors, evictions
```

Non-`obsolete` distilled entries proceed through the normal pipeline. The `obsolete` entries themselves are filtered out before `_dedup_and_merge` (they produce evictions, not map entries).

The `deterministic_cartographer` function gains a `stage_0` step and accumulates `obsolete_evictions` into the result:

```python
def deterministic_cartographer(...) -> CartographerResult:
    ...
    distilled_no_obsoletes = [d for d in distilled if d.observation_type != "obsolete"]
    working, obsolete_evictions = _stage_0_explicit_removals(distilled, current_map, cycle_n)
    working = _dedup_and_merge(distilled_no_obsoletes, working, cycle_n, config, timestamp)
    working = [_apply_priority(e, cycle_n, config) for e in working]
    working, stale_evictions = _evict_stale(working, cycle_n, config)
    working, budget_evictions = _enforce_budget(working, cycle_n, config)
    return CartographerResult(
        new_map=working,
        evictions=[*obsolete_evictions, *stale_evictions, *budget_evictions],
        cycle_n=cycle_n,
    )
```

### 2.4 Distiller prompt additions

The `distiller_v1.md` prompt (or its successor) adds to the observation_type list:

```
- `obsolete` — an existing map entry that is no longer true and should be
  removed entirely. Use the existing entry's key. The summary should explain
  why it became obsolete. Do NOT use this for corrections — use `dispute` when
  you have a corrected version of the claim.
```

---

## 3. Change 2 — Per-type decay configuration

### 3.1 Rationale

Today `staleness_penalty`, `staleness_floor`, `recency_bonus`, and `recency_cap` are global scalars. Every entry decays at the same rate and hits the same floor. This is wrong because:

- **`constant`** entries (magic numbers, config values) rarely change. They should decay very slowly and have a high floor.
- **`result`** entries (reusable computations) become stale quickly. They should decay fast and have a low floor.
- **`entity`** entries (class/function locations) are partially stable — files move but core concepts persist. Moderate decay.
- **`architecture`** entries (structural invariants) gain value over time — the longer a constraint holds, the more proven it is. They need high recency caps.

Per-type decay lets each type have its own age curve.

### 3.2 Config surface

`CartographerConfig` gains four new fields, each a `dict[str, float]` keyed by observation type. The existing scalar fields are **removed** (backward-incompatible — see migration §8).

```python
@dataclass(frozen=True, slots=True)
class CartographerConfig:
    token_budget: int = 1024
    tokenizer_name: str = "cl100k_base"

    # --- Per-type decay (replaces global scalars) ---
    staleness_penalty: dict[str, float]     # per observation_type
    staleness_floor: dict[str, float]       # per observation_type
    recency_bonus: dict[str, float]         # per observation_type
    recency_cap: dict[str, float]           # per observation_type

    priority_weights: dict[str, float]
    section_budget_share: dict[str, float]  # §4

    prompt_block: str = "structured"
    # ... cross_corpus fields unchanged
```

Default values per type:

| Type | `staleness_penalty` | `staleness_floor` | `recency_bonus` | `recency_cap` | Rationale |
|------|---------------------|-------------------|-----------------|---------------|-----------|
| `dispute` | 0.02 | 0.50 | 0.01 | 0.50 | Disputes are high-stakes — once corrected, the correction should persist |
| `schema` | 0.03 | 0.40 | 0.01 | 0.50 | Schema knowledge prevents tool failures; moderate decay |
| `insight` | 0.05 | 0.20 | 0.01 | 0.40 | Insights are valuable but can become stale |
| `architecture` | 0.01 | 0.60 | 0.01 | 0.80 | Cross-cutting invariants decay slowly, gain value with age |
| `boundary` | 0.02 | 0.30 | 0.01 | 0.30 | Boundaries (what is NOT present) are stable but narrow |
| `entity` | 0.05 | 0.20 | 0.01 | 0.50 | Moderate — files move but core concepts persist |
| `result` | 0.10 | 0.05 | 0.00 | 0.10 | Results stale quickly, zero recency bonus |
| `constant` | 0.01 | 0.60 | 0.01 | 0.30 | Constants rarely change; conservative decay |
| `obsolete` | N/A | N/A | N/A | N/A | Obsolete entries are removed in stage 0, never scored |

### 3.3 `_apply_priority` changes

The function reads per-type parameters instead of globals:

```python
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
```

`_evict_stale` reads `config.staleness_floor[entry.observation_type]`.

### 3.4 Validation

The config loader enforces that all four per-type dicts contain exactly the same keys as `priority_weights` (minus `obsolete`, which never enters scoring). Missing keys are a hard error.

---

## 4. Change 3 — `architecture` observation type

### 4.1 Rationale

None of the seven existing types captures cross-cutting structural invariants:

- `entity` says "X exists at path Y" — navigational.
- `insight` says "X relates to Y" — pairwise.
- `schema` says "X has shape S" — structural but data-focused.

`architecture` says "the system is organized according to principle P, and violating P causes category errors." Examples:

> ✅ **architecture:** "The context-map pipeline is Distiller → Cartographer → Evictor, strictly linear with no feedback loops."
>
> ✅ **architecture:** "The SOUL → Skills → Tools layering is strict — tools never call skills, skills never call SOUL directly."
>
> ✅ **architecture:** "The harness uses event sourcing — all state changes are append-only events replayed to reconstruct current state."
>
> ❌ **NOT architecture:** "The Cartographer receives Distiller output as input" → this is an `insight` (two specific components).
>
> ❌ **NOT architecture:** "`deterministic_cartographer()` lives in `cartographer.py`" → this is an `entity` (one thing).

### 4.2 Litmus test

**If removing or changing this fact would cause the agent to make a category error about how the system is organized, it's architecture.** If it's about where a specific thing lives, it's an entity. If it's about how two specific things interact, it's an insight.

The Distiller prompt makes this exclusive: "If the fact could also be classified as an insight about two specific components, use `insight`. If it could be classified as an entity (location of one component), use `entity`. Reserve `architecture` for cross-cutting structural invariants that govern many components."

### 4.3 Section assignment

`architecture` entries go to a new section: `context_architecture`.

```python
SECTION_MAP: dict[str, str] = {
    "schema":       "parsing_schema",
    "entity":       "context_understanding",
    "boundary":     "context_understanding",
    "insight":      "context_roadmap",
    "dispute":      "context_roadmap",
    "constant":     "domain_constants",
    "result":       "reusable_results",
    "architecture": "context_architecture",      # NEW
    # "obsolete" is never assigned a section — it's removed in stage 0
}
```

### 4.4 Distiller prompt update

Add to `observation_type` descriptions:

```
- `architecture` — a structural invariant that governs how the system is
  organized across multiple components. Use this ONLY when the fact describes
  a constraint, layering rule, or design commitment that shapes many
  decisions. If the fact describes a relationship between two specific
  components, use `insight` instead. If it describes the existence or location
  of a single component, use `entity`.
```

### 4.5 `observe` tool prompt update

The inline prompt in `harness_poc/core/runtime/pydantic_runtime.py` (line ~790) that describes observation types to the post-turn extractor must include `architecture` in its enum and description list. This is a two-line change.

### 4.6 New event type

A `MapEntryArchitectureObserved` event is NOT needed. Architecture entries are inserted via the existing `MapEntryInserted` event (which carries `observation_type` and `section`). The `observation_type: "architecture"` value in the event payload is sufficient for the calibration system to track architecture entries.

---

## 5. Change 4 — Section budget reservations

### 5.1 Rationale

Today `_enforce_budget` sorts all entries by global priority and takes the top N until the budget is exhausted. This means a section with many medium-priority entries can crowd out a section with few high-priority entries. Consider:

- 10 `entity` entries at priority 0.70 each = 500 tokens
- 3 `architecture` entries at priority 0.80 each = 150 tokens
- 5 `insight` entries at priority 0.90 each = 250 tokens

Under the current algorithm, the 5 insights enter first (450 tokens), then 3 architecture (150 tokens → 600 total), then ~8 entities (400 tokens → 1000 total). The remaining 2 entities and 2 insights are evicted. This is reasonable.

But over many cycles, if entities accumulate (20 entries at 0.65 after decay), they can consume 800+ tokens and squeeze out architecture entries that haven't been re-materialized recently. An architecture entry at floor 0.60 with no recency bonus competes badly against an entity entry at 0.65 with a recency bonus of 0.3 = 0.95.

The solution: each section gets a **guaranteed share** of the token budget. Within each section, entries still compete by priority. Unused share overflows to a global pool. Sections can self-evict (if a section has more entries than its share allows, the lowest-priority entries within that section are evicted).

### 5.2 Algorithm

```python
def _enforce_budget(
    entries: Sequence[MapEntry],
    cycle_n: int,
    config: CartographerConfig,
) -> tuple[list[MapEntry], list[EvictionRecord]]:
    # Group by section
    by_section: dict[str, list[MapEntry]] = {}
    for e in entries:
        by_section.setdefault(e.section, []).append(e)

    # Sort each section by priority desc
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
                evictions.append(EvictionRecord(
                    entry_id=entry.entry_id,
                    key=entry.key,
                    section=entry.section,
                    observation_type=entry.observation_type,
                    materialization_count=entry.materialization_count,
                    reason=f"budget@cycle={cycle_n},priority={entry.priority:.3f},section={section}",
                ))
        remaining_budget -= used

    # Pass 2: fill remaining budget from all sections by global priority
    all_remaining = []
    for section_entries in by_section.values():
        all_remaining.extend(section_entries)
    all_remaining.sort(
        key=lambda e: (-e.priority, -e.last_updated.timestamp(), e.entry_id)
    )

    for entry in all_remaining:
        if remaining_budget <= 0:
            evictions.append(EvictionRecord(...))
            continue
        if entry.token_estimate <= remaining_budget:
            survivors.append(entry)
            remaining_budget -= entry.token_estimate
        else:
            evictions.append(EvictionRecord(...))

    return survivors, evictions
```

### 5.3 Default shares

| Section | Share | Rationale |
|---------|-------|-----------|
| `context_architecture` | 0.25 | Small number of high-value structural invariants |
| `parsing_schema` | 0.20 | Schema entries prevent tool failures; moderate footprint |
| `context_understanding` | 0.25 | Entities + boundaries — workhorse navigational knowledge |
| `context_roadmap` | 0.15 | Insights + disputes — highest churn, valuable but volatile |
| `domain_constants` | 0.10 | Rarely changes, small footprint per entry |
| `reusable_results` | 0.05 | Ephemeral, lowest long-term value |

Shares sum to 1.0. The config loader enforces this.

### 5.4 Edge case: unfilled share overflow

If `context_architecture` is reserved 25% (256 tokens) but only contains 2 entries (100 tokens), the remaining 156 tokens flow to the global pool in Pass 2. Any section's entries can claim them by priority.

### 5.4.1 Edge case: single entry exceeds section share

If the highest-priority entry in a section has `token_estimate > section_budget`, it is evicted in Pass 1 and does **not** get a second chance in Pass 2 (it was popped from `by_section` and added to `evictions`). This means a single oversized architecture entry can be evicted even when the global remaining budget after Pass 1 would have accommodated it.

**Accepted trade-off:** Section entries that exceed their section's share are not rescued by Pass 2. This preserves the simplicity of the two-pass algorithm and is consistent with §5.5 — reservations guarantee minimum budget space, not accommodation of unbounded entry sizes. Operators who find important large-scope entries being evicted should either increase the section's share or split the entry into more granular observations.

### 5.5 Edge case: section self-eviction

If `context_understanding` is reserved 25% (256 tokens) but contains 8 entries totaling 400 tokens, the 4 lowest-priority entries are evicted during Pass 1. The section does NOT get an exemption — the reservation guarantees budget space, not unlimited entry count.

### 5.6 Config surface

```yaml
cartographer:
  section_budget_share:
    context_architecture: 0.25
    parsing_schema: 0.20
    context_understanding: 0.25
    context_roadmap: 0.15
    domain_constants: 0.10
    reusable_results: 0.05
```

The config loader validates that:

1. Every key in `section_budget_share` matches a known section name (a value appearing in `SECTION_MAP`).
2. Every section name that appears in `SECTION_MAP` has a corresponding entry in `section_budget_share` — a missing entry is a hard error, not a silent zero reservation.
3. Values sum to `1.0` within floating-point tolerance (±0.001).

The bidirectional check prevents a class of misconfiguration where a new observation type → section mapping is added without a budget share, which would silently push every entry in that section to Pass 2.

---

## 6. Configuration — Complete `harness.yaml` fragment

```yaml
distiller:
  model: deepseek/deepseek-chat
  max_retries: 3
  prompt_template: distiller_v2          # updated: includes architecture + obsolete

cartographer:
  token_budget: 1024
  tokenizer_name: cl100k_base

  # Per-type decay (replaces global recency_bonus/recency_cap/staleness_penalty/staleness_floor)
  staleness_penalty:
    dispute: 0.02
    schema: 0.03
    insight: 0.05
    architecture: 0.01
    boundary: 0.02
    entity: 0.05
    result: 0.10
    constant: 0.01

  staleness_floor:
    dispute: 0.50
    schema: 0.40
    insight: 0.20
    architecture: 0.60
    boundary: 0.30
    entity: 0.20
    result: 0.05
    constant: 0.60

  recency_bonus:
    dispute: 0.01
    schema: 0.01
    insight: 0.01
    architecture: 0.01
    boundary: 0.01
    entity: 0.01
    result: 0.00
    constant: 0.01

  recency_cap:
    dispute: 0.50
    schema: 0.50
    insight: 0.40
    architecture: 0.80
    boundary: 0.30
    entity: 0.50
    result: 0.10
    constant: 0.30

  priority_weights:
    dispute: 1.0
    schema: 0.9
    architecture: 0.85
    insight: 0.8
    boundary: 0.7
    entity: 0.6
    result: 0.5
    constant: 0.4

  section_budget_share:
    context_architecture: 0.25
    parsing_schema: 0.20
    context_understanding: 0.25
    context_roadmap: 0.15
    domain_constants: 0.10
    reusable_results: 0.05

  cross_corpus:
    enabled: true
    related_corpora:
      "deverino:codebase":
        - "deverino:dashboard"
        - "deverino:benchmarks"
    max_cross_entries: 16
    min_priority: 0.7
```

Notes:

- `obsolete` does not appear in any per-type decay dictionary (it never enters `_apply_priority` or `_evict_stale`).
- The global scalars `recency_bonus`, `recency_cap`, `staleness_penalty`, `staleness_floor` are removed. Configs using them will fail validation with a clear error ("use per-type decay dictionaries instead").
- `priority_weights` gains an `architecture` key.
- `section_budget_share` is a new top-level key under `cartographer`.

---

## 7. Calibration impact

### 7.1 `architecture` bootstrapping problem

`calibrate.py` iterates `_REQUIRED_WEIGHT_KEYS` (which will include `architecture`) and computes `target = base * (0.5 + ref_rate) * (0.5 + survival)`. For a newly-added type, `ref_rate ≈ 0` (no `MapEntryReferenced` events yet) and `survival` is undefined (no insertion or eviction data). The formula pushes the weight toward `base * 0.5 * 0.5 = 0.25`.

Mitigation: calibration treats zero-signal types conservatively — if `total_references` for a type is zero AND `mat_sum` is zero, the target weight is unchanged from the base weight. Only types with actual signal get tuned.

```python
if refs == 0 and mat_sum <= 1:  # mat_sum starts at 1 from the max(..., 1) guard
    target = base  # no signal → don't drift
else:
    target = base * (0.5 + ref_rate) * (0.5 + survival)
```

### 7.2 Per-type decay params are NOT calibrated

`calibrate.py` currently tunes only `priority_weights`. The four per-type decay dictionaries are config-only knobs that the operator tunes by hand. This is a deliberate choice: decay rates reflect domain knowledge ("constants rarely change"), not empirical observation. The calibration system already has enough degrees of freedom.

### 7.3 `section_budget_share` is NOT calibrated (yet)

Section shares reflect architectural judgment about knowledge categories. They could theoretically be tuned from eviction patterns (e.g., if `context_architecture` consistently underflows, reduce its share), but this is deferred to a future calibration pass. The initial shares are static defaults.

---

## 8. Migration plan

### 8.1 Schema changes (breaking)

| Change | Impact |
|--------|--------|
| `ObservationType` gains `"architecture"` and `"obsolete"` | New entries can have these types; existing entries remain valid |
| `SECTION_MAP` gains `"architecture" → "context_architecture"` | New section name in map |
| `CartographerConfig` gains per-type dict fields, loses scalar decay fields | **Breaking** — existing `harness.yaml` with `staleness_penalty: 0.05` fails validation |

### 8.2 Migration steps

1. **Add `architecture` and `obsolete` to `ObservationType` literal** in `harness_poc/core/context_map/schema.py` — backward-compatible (widening). In the same change, add `"architecture": 0.85` to the `_DEFAULT_PRIORITY_WEIGHTS` constant in `harness_poc/core/context_map/config.py` so any code path that instantiates `CartographerConfig` without an explicit `priority_weights` still has a complete weight table.
2. **Add `context_architecture` to `SECTION_MAP`** in `harness_poc/core/context_map/sections.py` — backward-compatible.
3. **Add stage 0 pass to Cartographer** — backward-compatible (no `obsolete` distillations → no-op).
4. **Add per-type decay config fields** to `CartographerConfig` using the per-type defaults from §3.2 / §6. These intentionally diverge from the prior globals (e.g. `constant` decays at 0.01 instead of the global 0.05, `result` decays at 0.10) — existing context maps will see different staleness behavior on the first cycle after upgrade. This is the point of the change; it is not a compatibility regression.
5. **Remove global scalar fields** from `CartographerConfig`.
6. **Update `load_cartographer_config`** to reject old-style scalar fields with a clear error.
7. **Write `distiller_v2.md`** prompt with `architecture` and `obsolete` descriptions.
8. **Update `observe` tool inline prompt** in `pydantic_runtime.py`.
9. **Update `harness.yaml`** to the new format.
10. **Add section budget reservation** to `_enforce_budget`.

### 8.3 Data migration

Existing context maps in the database use the old `ObservationType` literal (7 values). When new code reads these entries (e.g., during `db.get_context_map()`), the Pydantic model will accept them because the field type is `str` in the database and the `Literal` is only enforced at the Python schema level. However, `MapEntry.observation_type` is typed as `ObservationType`, so existing entries with the old 7 values will parse correctly — no database migration needed.

New entries with `observation_type: "architecture"` will be created normally. No existing entry is reclassified.

### 8.4 No retroactive reclassification

If 30 existing `entity` entries are actually architecture-level knowledge, they stay tagged as `entity`. The Distiller will re-classify them as `architecture` if the events that produced them are re-processed, but there is no one-off migration script. The practical impact is minor: those entries get entity-level protection (worse) instead of architecture-level protection until naturally re-materialized.

---

## 9. Open questions

### 9.1 Obsolete — empty map boundary case

When the Cartographer processes an `obsolete` entry whose key matches nothing in the current map, should it:

- **A) No-op silently** — the entry is already absent (evicted or never existed). No event emitted. Simpler, same end state.
- **B) Emit an `obsolete_miss` event** — records that something was declared obsolete but already absent. Useful for audit trails and debugging Distiller misbehavior.

**Decision: A (no-op silently).** The `prior_keys` list in the Distiller's input already limits `obsolete` to keys the Distiller knows are present; a miss is a race with a concurrent eviction, not misbehavior. The extra event type and handler add surface area for marginal audit value. The `EvictionRecord` produced in the normal case already provides a sufficient audit trail when a key is removed.

### 9.2 Per-type decay — which parameters?

Should all four decay parameters be per-type, or only staleness?

- **All four:** Architecture entries need different recency curves than results. Maximum flexibility. Config is verbose but auto-generated defaults cover most cases.
- **Staleness only:** `staleness_penalty` and `staleness_floor` per-type. `recency_bonus` and `recency_cap` stay global. Simpler config, but `result` entries can't have zero recency bonus.

**Decision: All four parameters become per-type.** The config verbosity is manageable (7 scored types × 4 params = 28 values). Disabling recency for ephemeral types (`result: recency_bonus=0.0`) and amplifying it for stable types (`architecture: recency_cap=0.80`) are the two behaviors that motivate this whole spec — splitting them off into "staleness only" loses the most important wins. Per §3.4 the loader requires explicit values for every scored type — defaults live in `harness.yaml` (§6), not in code, so operators see exactly what their system is doing.

### 9.3 Section budget reservation — unfilled share overflow

**Decision: Unfilled share flows to a global pool (Pass 2).** Any section's entries can claim leftover tokens by priority. Reservations guarantee minimums, not maximums. Note: entries that were *evicted* in Pass 1 (because they exceeded their section's share) are not rescued — see §5.4.1.

### 9.4 Architecture and recency bonus — direction

Should architecture entries have a *higher* recency cap than entities (as proposed: 0.80 vs 0.50)?

- **Higher cap (0.80):** The longer a structural invariant holds, the more proven it is. Architecture entries that survive 80 cycles should have high priority.
- **Same cap (0.50):** Simpler. Architecture is already protected by higher base weight (0.85) and lower staleness penalty (0.01).

**Decision: Higher cap (0.80).** With `recency_bonus=0.01` and `recency_cap=0.80`, an architecture entry needs ~80 cycles of presence to reach saturation (0.85 + 0.80 = 1.65). That curve matches the semantics: a structural invariant that has held across 80 distillation cycles has earned its place above transient knowledge. Disputes still dominate fresh corrections (1.0 + 0.50 = 1.50 max) which is correct — a brand-new correction should override an old architectural assumption. The higher cap also means architecture entries protect themselves against the entity tide described in §5.1 without needing operator intervention.

### 9.5 `observe` tool and post-turn extractor — update surface

Two places need `architecture` added:

1. `harness_poc/core/runtime/pydantic_runtime.py` — `extract_observations_from_turn()` system prompt and the inline `AutoObserveEntry` Pydantic model's `observation_type` field (currently `Literal[...]` over 7 types around lines 780–808).
2. The `observe` skill's input schema (`skills/observe/SKILL.md` argument enum, if present, plus any Pydantic validator in `skills/observe/skill.py`).

**Decision: `architecture` is added to both; `obsolete` is added to neither.** The post-turn extractor sees a single conversation turn, not the context map, so it has no `prior_keys` and cannot safely assert that a key is obsolete. The `observe` skill is the same — it's an opportunistic capture path during normal agent runs, not a reconciliation pass. `obsolete` remains Distiller-only because the Distiller is the only call site that receives the current map as input.

### 9.6 Calibration — zero-signal type handling

Should calibration treat `architecture` specially during bootstrapping, or rely on the general zero-signal guard described in §7.1?

**Decision: Rely on the general zero-signal guard.** Per `calibrate.py` (`run_calibration`, lines 36–134), `mat_sum` is already floored at 1 via `max(materialization_count, 1)`, so the guard `if refs == 0 and mat_sum <= 1: target = base` cleanly identifies any type that has never been referenced and never materialized beyond the floor. This applies uniformly to `architecture`, to any future new type, and to incumbent types that happen to receive zero signal in a calibration window. Special-casing `architecture` would couple the calibrator to the type taxonomy, which contradicts its design as a generic signal-to-weight mapper.

### 9.7 Section budget share — tunable later?

Section shares are static config today. Should calibration eventually learn them from eviction patterns?

- **Pro:** A section that consistently underflows (e.g., `reusable_results` only ever uses 2% of budget) can have its share reduced automatically, freeing budget for over-pressured sections.
- **Con:** Shares encode architectural judgment. Automating them risks the system optimizing for the wrong signal (e.g., reducing `context_architecture` share because few entries exist, even though those few are critically important).

**Decision: Defer to a future spec.** Keep shares as operator-tuned config in this iteration. Revisit only after we have at least one full milestone of `_enforce_budget` Pass-1 vs Pass-2 telemetry showing consistent over/underflow patterns. A separate spec at that point can decide whether to add a `section_share` calibrator and which signal (eviction rate, overflow rate, reference rate per section) it should optimize against.

---

## 10. Implementation sequence

| Step | What | Dependencies |
|------|------|-------------|
| 1 | Add `architecture`, `obsolete` to `ObservationType` literal | None |
| 2 | Add `context_architecture` to `SECTION_MAP` | Step 1 |
| 3 | Write `distiller_v2.md` prompt | Step 1 |
| 4 | Add stage 0 obsolete pass to Cartographer | Step 1 |
| 5 | Add per-type decay fields to `CartographerConfig`; update `_apply_priority`, `_evict_stale` | Step 1 |
| 6 | Add section budget reservation to `_enforce_budget` | Step 2 |
| 7 | Update `load_cartographer_config` — reject old scalars, validate new dicts | Steps 5, 6 |
| 8 | Update `observe` tool prompt in `pydantic_runtime.py` | Step 1 |
| 9 | Update `harness.yaml` to new format | Steps 5, 6, 7 |
| 10 | Calibration zero-signal guard | Step 5 |
| 11 | Unit tests for stage 0, per-type decay, section reservation | Steps 4, 5, 6 |
| 12 | Contract tests for distiller_v2 prompt | Step 3 |
