# Context Map Eviction Findings

**Date:** 2025-07-17  
**Experiment:** Force eviction of lowest-priority entry via observation pressure

---

## Baseline State (Cycle 58)

8 entries, token count ~850+, budget 1024 tokens.

### Entry Summary

| # | Key | Section | Type | Priority | Tokens |
|---|---|---|---|---|---|
| 1 | cartographer-eviction-record-format | parsing_schema | schema | 0.91 | ~40 |
| 2 | cartographerconfig-refactoring | parsing_schema | schema | **0.57** | ~50 |
| 3 | calibration-run-calibration | context_roadmap | entity | 0.60 | ~60 |
| 4 | two-pass-budget-enforcement | context_architecture | architecture | 0.88 | ~80 |
| 5 | priority-formula | context_architecture | architecture | 0.86 | ~75 |
| 6 | observation-types | context_understanding | entity | 0.65 | ~55 |
| 7 | lru-cache-encoder | context_understanding | entity | 0.63 | ~40 |
| 8 | distiller-agent | context_understanding | entity | 0.68 | ~60 |

The **lowest-priority entry** was `cartographerconfig-refactoring` at **p=0.57**, in the `parsing_schema` section.

---

## Campaign Execution

### Observations Added (~25 total, across 8 modules)

| Module | Observation Types | Count |
|---|---|---|
| `cartographer.py` | architecture, entity, insight | 5 |
| `calibrate.py` | schema, entity, insight | 4 |
| `config.py` | schema, entity, constant | 3 |
| `sections.py` | architecture, boundary | 2 |
| `dashboard.py` | entity, schema | 2 |
| `goal_runner.py` | entity, schema, insight | 4 |
| `skill_runner.py` | entity | 1 |
| `permissions.py` | architecture | 1 |
| `models.py` | constant, schema | 2 |
| `context_map_events.py` | schema | 1 |
| `cli.py` | entity | 1 |
| `tui.py` | entity | 1 |

### Materialization History

| Cycle | Entries | Tokens | Events Processed | Δ |
|---|---|---|---|---|
| 58 (baseline) | 8 | ~850 | — | — |
| 62 | 9 | 843 | 5 | +1 entry |
| 63 | 9 | — | — | pending |
| 64 | 9 | 814 | 16 | dedup |
| 67 | 9 | 819 | 16 | stable |
| 69 | 9 | 836 | 10 | +new entries |
| 71 | 9 | 823 | 16 | compaction |
| **74** | **8** | **752** | 21 | **eviction** |
| 75 | 8 | 752 | 15 | stable |
| 76 | 8 | 752 | — | pending |

**Net result:** 0 net entry change (8 → 8), but significant churn — one entry was evicted and replaced, and token count compacted by ~100 tokens.

---

## Key Findings

### 1. The Distiller Merges Aggressively

The distiller LLM pass produces far fewer DistillerEntries than raw observation events. Adding 25 observations across 8 modules resulted in only ~1-2 net new entries per cycle. Observations about the same module (even different files within it) were often merged into a single entry.

- **Implication:** To force eviction, observations must span truly unrelated modules, not just different files in the same conceptual area.
- **Implication:** The distiller's merging behavior is the dominant constraint on map growth — not the cartographer's budget enforcement.

### 2. Token Budget Slack Absorbs Moderate Pressure

The budget (1024 tokens) with 8-9 entries (~750-850 tokens) left ~200 tokens of slack. This slack absorbed several rounds of observation pressure before an eviction occurred. At cycle 71, the map was at 9 entries / 823 tokens — still under budget.

- **Implication:** The budget is not the active constraint during normal operation. Most evictions will come from staleness, not budget pressure, unless the map grows significantly.
- **Implication:** To reliably trigger budget eviction, one must add enough distinct entries to push well past 1024 tokens.

### 3. The Eviction Happened at Cycle 74

The entry count dropped from 9 → 8 between cycles 71 and 74, with token count simultaneously dropping from 823 → 752. This suggests:

1. The lowest-priority entry (p=0.57 CartographerConfig refactoring) was evicted in Pass 2 of `_enforce_budget`
2. The distiller simultaneously compacted remaining entries, reducing token count by ~71 tokens

### 4. Two Caching Strategies Coexist

`cartographer.py` uses `@lru_cache(maxsize=4)` for tiktoken encoder caching. `goal_runner.py` uses a module-level `_encoder_cache` dict. Two different approaches to the same problem in the same codebase.

### 5. Section Budget Shares Have Slack

The `domain_constants` (10%) and `reusable_results` (5%) sections had zero entries throughout the experiment. Their budget (~153 tokens) flows to the global pool in Pass 2, giving other sections extra headroom. This means the effective budget for populated sections is larger than their nominal shares.

### 6. Dedup Uses Strict Superset Logic

`_is_strict_superset` at `cartographer.py:149-151` only updates an entry's summary when the new DistillerEntry's `source_event_ids` are a strict superset of the existing MapEntry's. Equal or subset event IDs result in only a `materialization_count` bump with no summary update. This preserves the most-evidenced version of each fact.

---

## Methodology Notes

- The context map in the agent's prompt is a snapshot from turn-start and does not update mid-turn. Post-materialization state must be inferred from `list_corpora` and materializer output.
- Citation of entries via `[entry:<id>]` is the mechanism by which the harness learns which entries are useful. Uncited entries are demoted over time via the staleness penalty.
- The `observe` tool queues raw events; the `context-map-materializer` runs Distiller → Cartographer → Evictor to produce the final map.

---

## Raw Data

### Final Map State (Cycle 76)

- **Entries:** 8
- **Tokens:** 752
- **Budget:** 1024
- **Slack:** 272 tokens (26.5%)
- **Pending events:** yes
