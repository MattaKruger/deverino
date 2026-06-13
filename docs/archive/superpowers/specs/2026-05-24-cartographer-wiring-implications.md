# Cartographer Wiring Implications

**Date:** 2026-05-24
**Status:** Notes for follow-up wiring spec
**Parent spec:** `docs/superpowers/specs/2026-05-23-deterministic-cartographer-design.md`
**Parent plan:** `docs/superpowers/plans/2026-05-23-deterministic-cartographer.md`

Documents the harness-level changes the Deterministic Cartographer implementation requires.
The Cartographer engine itself is built and tested; this captures what the next spec must wire.

## 1. Stale component: `context-map-materializer` skill

**File:** `skills/context-map-materializer/skill.py`

Currently performs two LLM calls — Distiller then Cartographer — plus a separate deterministic budget eviction.
The LLM Cartographer call is the _deliberation cascade_ anti-pattern the design eliminates.

**Required rewrite:**

```python
# Today (two LLM calls + separate budget eviction):
distiller_raw = chat_text(_distiller_messages(...), model=model)       # LLM
cartographer_raw = chat_text(_cartographer_messages(...), model=model)  # LLM (cascade)
candidate_map, evictions = _enforce_budget(candidate_map, token_budget) # deterministic

# Tomorrow (one LLM call → deterministic cartographer):
entries = await run_distiller(events, model, config.distiller)           # LLM
result = deterministic_cartographer(entries, current_map, cycle_n, config.cartographer)
```

Key changes within the skill:

- Replace `_distiller_messages()` / `_cartographer_messages()` / `_apply_edits()` / `_enforce_budget()` / `_detect_promotions()` with calls into `harness_poc.core.context_map`.
- The Distiller model comes from `config.distiller.model` (falls back to `config.llm` if `None`).
- Token budget comes from `config.cartographer.token_budget`, not `RuntimeConfig.materializer_token_budget`.
- Cycle number (`cycle_n`) must be tracked — either stored in the database per corpus key or inferred from map version.
- `CartographerResult.evictions` must be converted into `MapEntryEvicted` events and appended via `db.append_context_map_event()`.

## 2. Config surface shift

| Config value | Current source | New source |
|---|---|---|
| Token budget | `RuntimeConfig.materializer_token_budget` | `CartographerConfig.token_budget` |
| Max event tokens (Distiller input) | `RuntimeConfig.materializer_max_event_tokens` | Stays in `RuntimeConfig` |
| Distiller model | `LLMConfig` (primary model) | `DistillerConfig.model` (falls back to `LLMConfig`) |
| Priority weights, recency, staleness | Hardcoded in skill | `CartographerConfig` (loaded from `harness.yaml`) |

`RuntimeConfig.materializer_token_budget` becomes vestigial after the skill rewrite.
Keep the field for backward compat until the wiring spec is complete, then remove.

## 3. Map schema migration

**Old format** (dict-of-dicts, persisted in database):
```json
{
  "parsing_schema": {
    "some-key": {"entry_id": "abc123", "content": "...", "priority_score": 0.5}
  },
  ...
}
```

**New format** (list of MapEntry Pydantic models):
```json
[
  {
    "entry_id": "uuid",
    "key": "some-key",
    "section": "parsing_schema",
    "observation_type": "schema",
    "summary": "...",
    "priority": 0.9,
    "source_event_ids": ["ev-1"],
    "first_seen": "2026-05-24T00:00:00Z",
    "last_updated": "2026-05-24T00:00:00Z",
    "materialization_count": 3,
    "first_seen_cycle": 0,
    "last_seen_cycle": 5,
    "token_estimate": 12
  }
]
```

**Affected database methods** (`BlackboardDatabase`):

- `get_context_map(corpus_key)` — must deserialize into `list[MapEntry]`
- `write_map_and_mark_processed(...)` — must accept `list[MapEntry]` and serialize
- `get_pending_context_map_events(...)` — may need to filter/order differently for the Distiller

## 4. Prompt injection changes

**File:** `harness_poc/app_factory.py`, `_system_message_for()` / `build_runtime_layer()`

Currently:
```python
context_map = identity.database.get_context_map(corpus_key)
context_map_block = f"--- Context Map ---\n{json.dumps(context_map, indent=2)}\n---"
```

The new flat `MapEntry` schema changes what the agent sees. The design defers this to a future spec for ACDL `ContextMapBlock` injection. Until then, the wiring spec should either:
- Serialize `MapEntry` to a JSON string compatible with the current prompt format, or
- Defer the prompt format change alongside ACDL injection.

## 5. Token estimation dependency

**Old:** `len(json.dumps(map)) // 4` (character ÷ 4 heuristic).

**New:** `tiktoken`-based encoding via `cl100k_base`. This is more accurate but means `tiktoken` is now a **runtime dependency**, not just a dev dependency used during test tokenization. Verify `tiktoken` is listed in `pyproject.toml` dependencies (not just dev-dependencies).

## 6. Event emission

The Cartographer returns `CartographerResult.evictions: list[EvictionRecord]`. The wiring spec must:

1. Convert each `EvictionRecord` into a `MapEntryEvicted` event.
2. Append all such events via `db.append_context_map_event()`.
3. (Deferred) Emit `MapEntryReferenced` when the agent's response cites a map entry. The event class is defined; the wiring to detect citations in agent output is a future spec.

## 7. Materializer freeze/threshold interaction

`MaterializerRunner` tracks "no change" cycles per corpus key. Currently detects change via `result.artifacts.get("map_changed")` from the skill's `SkillResult`.

With the new Cartographer, "change" detection moves to entry-level comparison:
- Compare `result.new_map` vs `current_map` via `model_dump_json()` equality, or
- Compare the set of `(key, summary, source_event_ids)` tuples.

The freeze threshold and duration (`materializer_freeze_threshold`, `materializer_freeze_seconds`) remain in `RuntimeConfig` and continue to operate as before.

## 8. Cross-corpus interaction (deferred)

The design spec explicitly defers cross-corpus insight handling. The current implementation produces one map per `corpus_key`. No wiring change needed for this — the Cartographer is already a pure function that operates on a single map.

## Summary: what the wiring spec must deliver

| # | Item | Priority |
|---|------|----------|
| 1 | Rewrite `context-map-materializer` skill to use `run_distiller()` + `deterministic_cartographer()` | **Required** |
| 2 | Point `MaterializerRunner` arguments at `config.cartographer` / `config.distiller` | **Required** |
| 3 | Migrate database map serialization to `list[MapEntry]` format | **Required** |
| 4 | Convert `EvictionRecord` → `MapEntryEvicted` events in the skill | **Required** |
| 5 | Track `cycle_n` per corpus key (database or in-memory) | **Required** |
| 6 | Handle `context_map_block` prompt injection for new map format | **Deferred** (bundled with ACDL injection) |
| 7 | Wire `MapEntryReferenced` event emission | **Deferred** (future spec) |
| 8 | Remove vestigial `RuntimeConfig.materializer_token_budget` | **Cleanup** (after wiring confirmed) |
| 9 | Verify `tiktoken` is a runtime dependency | **Prerequisite** |
