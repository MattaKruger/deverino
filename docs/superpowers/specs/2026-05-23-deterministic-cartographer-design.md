# Deterministic Cartographer — Implementation Design

**Date:** 2026-05-23
**Status:** Approved for implementation planning
**Source skill:** `skills/deterministic-cartographer/SKILL.md`
**Source paper:** Kunz et al. (2025), *Compound Agent Design in Adversarial POMDPs* (2605.16205)

## 1. Purpose & Scope

Replace the LLM-based Cartographer/Evictor stages of the context-map pipeline with a deterministic Python engine. The LLM is retained only at the perception stage (the Distiller), which produces structured observations under a strict output schema. Deterministic code then handles dedup, priority scoring, staleness decay, section assignment, and token-budget eviction.

This is grounded in the paper's three principles: invest in deterministic infrastructure before LLM reasoning; decompose into bounded specialists with verifiable interfaces; do not distribute deliberation without an arbitration protocol. The current pipeline (LLM Distiller → LLM Cartographer → deterministic Evictor) exhibits the *deliberation cascade* anti-pattern: an LLM reasoning over another LLM's qualified output. Collapsing the second LLM into deterministic code eliminates the cascade.

### In scope

- The `DistillerEntry` and `MapEntry` schemas (Pydantic models).
- The Distiller — an LLM call with structured output, validation, and bounded retry.
- The deterministic Cartographer — a pure function over `(distilled, current_map, cycle_n, config)`.
- Section assignment (deterministic table).
- Priority scoring, staleness decay, budget enforcement.
- Telemetry events (`MapEntryReferenced`; structured `MapEntryEvicted.reason`).
- Configuration surface in `harness.yaml`.
- Unit tests for the Cartographer; contract tests for the Distiller.

### Out of scope (deferred)

- Event-store retrieval (how raw events reach the Distiller).
- Persistence of `current_map` between cycles.
- Event-bus emission of `MapEntryReferenced` / `MapEntryEvicted` (the spec defines the events; future spec wires emission).
- ACDL `ContextMapBlock` injection into the agent prompt.
- Cross-corpus insight handling — one map per `corpus_key` for now; cross-corpus is a future spec.
- Adaptive priority-weight learning — telemetry is emitted now; learning logic is a future spec.

## 2. Architectural Shape

```
[ContextMapEvent...]  ──►  Distiller (LLM, output_type=DistilledBatch)
                                            │
                                            ▼  (validated, retried up to N=3)
                                    list[DistillerEntry]
                                            │
                                            ▼
        deterministic_cartographer(distilled, current_map, cycle_n, config)
                                            │
                                            ▼
                          CartographerResult(new_map, emitted_events)
```

The Cartographer is a **pure function**. It takes the cycle counter as input (caller-owned), returns the events it *would* emit (caller actually emits). No I/O, no event-bus access, no clock. This is the seam the future wiring spec plugs into.

### Module layout

New package `harness_poc/core/context_map/`:

| File | Responsibility |
|---|---|
| `__init__.py` | Public exports: `run_distiller`, `deterministic_cartographer`, schema types, config types |
| `schema.py` | `DistillerEntry`, `MapEntry`, `CartographerResult`, `DistilledBatch` |
| `distiller.py` | `run_distiller(events, model, config) -> list[DistillerEntry]` |
| `cartographer.py` | `deterministic_cartographer(...) -> CartographerResult` |
| `sections.py` | `SECTION_MAP` constant + `assign_section(observation_type) -> str` |
| `config.py` | `DistillerConfig`, `CartographerConfig` (Pydantic, loaded from `HarnessConfig`) |

Edits to existing files:

| File | Edit |
|---|---|
| `harness_poc/core/events/context_map_events.py` | Add `MapEntryReferenced`; widen `MapEntryEvicted` with `materialization_count: int` and structured `reason` |
| `harness_poc/core/config.py` | Add `distiller`, `cartographer` blocks to `HarnessConfig` |
| `harness.yaml` | Add config defaults (see §6) |
| `tests/context_map/` | New test directory (see §8) |

No edits to processors, skills, runtime, or REPL/TUI in this spec.

## 3. Schemas

```python
# harness_poc/core/context_map/schema.py
from __future__ import annotations
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field

ObservationType = Literal["entity", "schema", "insight", "dispute", "boundary", "constant", "result"]
Tag = Literal["confirmed", "novel", "correcting"]


class DistillerEntry(BaseModel):
    """A single observation emitted by the Distiller LLM call."""
    key: str = Field(..., description="Stable slug, e.g. 'codebase-entry-point'")
    observation_type: ObservationType
    summary: str = Field(..., description="One-paragraph orientation fact")
    source_event_ids: list[str] = Field(..., min_length=1)
    tags: list[Tag] = Field(default_factory=list)
    # Explicitly forbidden: section, priority, operation hints — those belong to the Cartographer.


class DistilledBatch(BaseModel):
    """Top-level output_type passed to the Distiller LLM call."""
    entries: list[DistillerEntry]


class MapEntry(BaseModel):
    """A materialized context-map row."""
    entry_id: str  # UUID, stable across map versions
    key: str
    section: str  # Assigned deterministically
    observation_type: ObservationType
    summary: str
    priority: float
    source_event_ids: list[str]
    first_seen: datetime
    last_updated: datetime
    materialization_count: int = 0  # Cycles survived
    first_seen_cycle: int  # cycle_n at insertion; used for recency bonus
    last_seen_cycle: int  # cycle_n at which this entry last appeared in distiller output
    token_estimate: int  # Cached len(tokenize(summary)); see §4.4


class EvictionRecord(BaseModel):
    entry_id: str
    key: str
    section: str
    observation_type: ObservationType
    materialization_count: int
    reason: str  # Structured: "stale@cycle=N,age=M,type=X" or "budget@cycle=N,priority=P"


class CartographerResult(BaseModel):
    new_map: list[MapEntry]
    evictions: list[EvictionRecord]  # The caller turns these into MapEntryEvicted events
    cycle_n: int
```

## 4. Algorithm

`deterministic_cartographer(distilled, current_map, cycle_n, config) -> CartographerResult` runs four operations in order. Each operation is a pure transformation on the working map.

### 4.1 Dedup & merge

Index `current_map` by `key`. For each entry in `distilled`:

- **New key** → insert a fresh `MapEntry`: `entry_id = uuid4()`, `first_seen = now`, `last_updated = now`, `materialization_count = 1`, `last_seen_cycle = cycle_n`, `priority = base_weight[observation_type]`.
- **Existing key**, newer `source_event_ids` → replace `summary`, `source_event_ids`, `last_updated = now`, increment `materialization_count`, update `last_seen_cycle = cycle_n`. Keep `entry_id` and `first_seen` stable.
- **Existing key**, same/older `source_event_ids` → no-op (still update `last_seen_cycle` and increment `materialization_count` to credit survival).

"Newer" is defined as: the multiset of `source_event_ids` is not a subset of the existing entry's. Equivalent sets are no-ops.

### 4.2 Priority scoring

For every entry in the working map (whether refreshed this cycle or not):

```
priority = base_weight[observation_type]
         + recency_bonus * (cycle_n - first_seen_cycle)        # capped at recency_cap
         - staleness_penalty * (cycle_n - last_seen_cycle)     # missed cycles since last refresh
```

`first_seen_cycle` is set at insertion (§4.1) and stored on `MapEntry` to keep the priority function free of wall-clock dependence.

### 4.3 Staleness eviction

Any entry whose `priority < config.staleness_floor` is evicted. An `EvictionRecord` is emitted with `reason = f"stale@cycle={cycle_n},age={cycle_n - last_seen_cycle},type={observation_type}"`.

### 4.4 Budget enforcement

Sort the surviving map by `priority` descending (stable sort; ties broken by `last_updated` descending, then `entry_id` ascending). Accumulate `token_estimate` until the next entry would exceed `config.token_budget`. Evict the tail; emit `EvictionRecord` with `reason = f"budget@cycle={cycle_n},priority={priority:.3f}"`.

`token_estimate` is computed once at insertion/refresh using a configured tokenizer (`config.tokenizer_name`, default `cl100k_base` via `tiktoken`). The Cartographer never tokenizes during scoring.

### 4.5 Determinism guarantees

- No `random`, no `time.time()` inside the pure function. All temporal inputs are passed as `cycle_n` and pre-computed `datetime` fields on `MapEntry` (set by the caller or at insertion).
- Stable tie-breaking — equal-priority entries always sort identically across runs.
- Given identical `(distilled, current_map, cycle_n, config)`, the function returns byte-identical `CartographerResult`.

This property is asserted by a `test_determinism` test (§8).

## 5. Distiller

### 5.1 Contract

```python
# harness_poc/core/context_map/distiller.py
async def run_distiller(
    events: list[ContextMapEvent],
    model: pydantic_ai.models.Model,
    config: DistillerConfig,
) -> list[DistillerEntry]: ...
```

The Distiller wraps a `pydantic_ai.Agent` with `output_type=DistilledBatch`. It receives a rendered prompt (events serialized to a compact JSON listing) and the system instruction defined in `distiller.py` as a module-level constant.

### 5.2 System prompt (v1)

The prompt instructs the LLM to:

1. Read every event.
2. Emit zero or more `DistillerEntry` objects.
3. Use stable `key` slugs (it MUST reuse an existing key from `prior_keys` if the observation refers to the same thing — `prior_keys` is injected as part of the prompt).
4. NOT assign sections, priorities, or operations — those belong to the Cartographer.
5. Cite at least one `source_event_id` per entry.

A complete prompt template is shipped as `harness_poc/core/context_map/prompts/distiller_v1.md` for ease of iteration.

### 5.3 Validation & retry

PydanticAI's `output_type=DistilledBatch` enforces schema at the agent level. Beyond that:

- **Additional validation** in `run_distiller`: every `source_event_id` MUST exist in the input `events` list. Unknown IDs trigger retry.
- **Retry budget**: `config.max_retries` (default 3). Each retry re-runs the agent with the prior error injected as a follow-up user message: `"Previous output was rejected: <error>. Reissue conforming output."`
- **Safe fallback**: after `max_retries` exhausted, `run_distiller` returns `[]`. The Cartographer's contract handles an empty `distilled` cleanly (no merges; staleness still applies). The caller logs the failure and proceeds with the prior map. This matches the paper's `Monitor` fallback: preserve observability, do no harm.
- **Token accounting**: retries count against the Distiller's per-cycle token budget if one is configured. v1 ships without a hard token budget on the Distiller; this is a future hardening.

### 5.4 Model selection

`DistillerConfig.model` is a string in the form `<provider>/<model>` (matching `harness.yaml` provider syntax). If unset, the Distiller falls back to `HarnessConfig.llm.primary_model`. The recommended default in `harness.yaml` is `anthropic/claude-haiku-4-5` for cost/latency parity with the paper's findings on structured-output Distiller-class tasks.

## 6. Configuration

Additions to `harness.yaml`:

```yaml
distiller:
  model: anthropic/claude-haiku-4-5   # Defaults to llm.primary_model if unset
  max_retries: 3
  prompt_template: distiller_v1       # Resolves to prompts/distiller_v1.md

cartographer:
  token_budget: 1024
  tokenizer_name: cl100k_base
  recency_bonus: 0.01
  recency_cap: 0.5                    # Maximum cumulative recency bonus per entry
  staleness_penalty: 0.05
  staleness_floor: 0.2
  priority_weights:
    dispute: 1.0
    schema: 0.9
    insight: 0.8
    boundary: 0.7
    entity: 0.6
    result: 0.5
    constant: 0.4
```

These are loaded into `HarnessConfig.distiller: DistillerConfig` and `HarnessConfig.cartographer: CartographerConfig`. Both Pydantic models use `extra="forbid"` to fail loudly on typos.

## 7. Events (additions)

In `harness_poc/core/events/context_map_events.py`:

```python
class MapEntryReferenced(ContextMapEvent):
    """Emitted by future wiring spec when the agent's response cites a map entry.
    Defined here so the schema is stable; emission lives elsewhere."""
    event_type: Literal["map_entry_referenced"] = "map_entry_referenced"
    entry_id: str
    entry_key: str
    section: str
    cycle_n: int
    citation_context: str  # Snippet of agent output that cited the entry


class MapEntryEvicted(ContextMapEvent):
    # Existing fields preserved; additions:
    materialization_count: int = 0
    # `reason` becomes a structured string; documented format:
    #   stale@cycle=N,age=M,type=X
    #   budget@cycle=N,priority=P
```

Both events are added to `CONTEXT_MAP_EVENT_REGISTRY`.

## 8. Testing

New directory `tests/context_map/`:

| Test file | Coverage |
|---|---|
| `test_schema.py` | Schema round-trip; rejection of forbidden fields on `DistillerEntry` (section, priority, operation hints) |
| `test_sections.py` | `assign_section` returns the documented mapping for all 7 observation types; raises on unknown |
| `test_cartographer_dedup.py` | New key inserts; existing key with newer events replaces; same events no-op; subset detection |
| `test_cartographer_priority.py` | Priority formula correctness across all 7 observation types; recency cap; staleness penalty |
| `test_cartographer_eviction.py` | Staleness floor triggers eviction with correct `reason` string; budget eviction sorts and trims correctly; tie-breaking is stable |
| `test_cartographer_determinism.py` | Same inputs → byte-identical `CartographerResult.model_dump_json()` across 100 invocations |
| `test_distiller_contract.py` | Mocked PydanticAI agent: valid output passes; invalid output triggers retry; 3 failed retries returns `[]`; unknown `source_event_id` triggers retry |
| `test_config.py` | `harness.yaml` defaults load correctly; `extra="forbid"` rejects typos |

No live LLM calls in tests. The Distiller test uses a `pydantic_ai.models.test.TestModel` or equivalent stub.

Invariants asserted by `test_cartographer_invariants.py` (example-based, table-driven; Hypothesis is not a current project dep and is not introduced by this spec):

- The output map's total `token_estimate` ≤ `token_budget`.
- No entry with `priority < staleness_floor` appears in `new_map`.
- Every `EvictionRecord` corresponds to an entry that was in `current_map` or freshly distilled this cycle.
- `entry_id` is stable across cycles for entries that survive.

## 9. Migration & rollout

Because no Cartographer currently exists in code (only the event schemas), this is a greenfield implementation, not a migration. Cutover proceeds in two phases — both fully covered by this spec:

1. **Phase 1 — Schemas + Cartographer + tests.** Land `harness_poc/core/context_map/` with full unit coverage. No runtime integration. CI runs the new tests.
2. **Phase 2 — Distiller.** Land `distiller.py` with the contract tests. PydanticAI agent wired against a configured model; no event-store reads yet (caller supplies events).

A future spec handles event-store fetch, persistence of `current_map`, event-bus emission, and ACDL `ContextMapBlock` injection.

## 10. Decisions (resolved open questions)

| # | Question | Decision | Rationale |
|---|---|---|---|
| 1 | Priority weight tuning | Fixed defaults + `MapEntryReferenced` telemetry | Principle 1 (deterministic now); preserves learning option |
| 2 | Section assignment granularity | 7 obs types → 5 sections, as in skill | Doubling-up is semantically defensible; clean render |
| 3 | Staleness decay rate | Defaults + structured `MapEntryEvicted.reason` for empirical calibration | Already paying the event cost; carry enough info to tune |
| 4 | Multi-corpus interaction | One map per `corpus_key`; cross-corpus deferred | Avoids coupling dedup logic; future spec handles cross-corpus |
| 5 | Distiller model choice | Dedicated `distiller.model` in config, defaults to primary | Decouples perception cost from reasoning cost; haiku-class is the right tool |
| 6 | Spec scope | Cartographer + Distiller contract; defer wiring | Reviewable unit; matches the swap point the skill argues for |
| 7 | Cartographer state shape | Pure function | Cleanest seam for wiring spec; trivially testable |

## 11. References

- `skills/deterministic-cartographer/SKILL.md`
- Kunz et al. (2025): `docs/papers_2/2605.16205.pdf`
- `docs/superpowers/specs/2026-05-20-event-sourced-context-map-design.md`
- `docs/superpowers/specs/2026-05-20-context-map-implementation-spec.md`
- `docs/superpowers/specs/2026-07-23-context-map-freeze-derivation-ids.md`
- `harness_poc/core/events/context_map_events.py` (existing events file extended by this spec)
