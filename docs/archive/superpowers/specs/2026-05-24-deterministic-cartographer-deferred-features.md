# Deterministic Cartographer — Deferred Features Design

**Date:** 2026-05-24
**Status:** Approved for implementation planning
**Part 1 spec:** `docs/superpowers/specs/2026-05-23-deterministic-cartographer-design.md`
**Wiring notes:** `docs/superpowers/specs/2026-05-24-cartographer-wiring-implications.md`

## 1. Purpose & Scope

Part 1 landed the pure Cartographer engine and Distiller contract. This spec covers everything Part 1 explicitly deferred. It splits naturally into two tracks:

- **Track A — Wiring.** Mechanical work needed before the engine is actually invoked in production: skill rewrite, database migration, cycle tracking, event emission, config cleanup. Without these, the engine is unreachable code.
- **Track B — Capability extensions.** Net-new behavior that the engine enables but does not require: prompt-side `ContextMapBlock` injection, `MapEntryReferenced` citation detection, cross-corpus insight handling, adaptive priority-weight learning.

Track A is sequenced first because every Track B feature assumes the engine is live.

### In scope

- Replacing `skills/context-map-materializer/skill.py` with a thin adapter over `harness_poc.core.context_map`.
- Migrating `BlackboardDatabase` map storage from `dict[section, dict[key, dict]]` to `list[MapEntry]`.
- Per-corpus cycle counter (`cycle_n`) — durable, monotonic.
- Wiring `EvictionRecord` → `MapEntryEvicted` event emission with the structured `reason` format from Part 1 §4.3/§4.4.
- ACDL `ContextMapBlock` injection (replacing the ad-hoc JSON dump in `_system_message_for`).
- `MapEntryReferenced` citation detection and event emission.
- Cross-corpus reader (read-only joins across maps; no merging of entries).
- Adaptive priority-weight learning loop (offline calibration from `MapEntryReferenced` / `MapEntryEvicted` counts).
- Removal of vestigial `RuntimeConfig.materializer_token_budget` and `MapEntryPromoted` derivation logic.

### Out of scope

- Changes to the Cartographer or Distiller algorithms themselves (Part 1 is frozen).
- New retrieval backends or document-source changes.
- LLM-side tool use that mutates the map outside the materializer skill.
- Multi-tenant isolation of corpus keys (single-tenant assumption holds).

## 2. Architectural Shape

```
                                    ┌──────────────────────────────────┐
                                    │  context-map-materializer skill  │
                                    │  (Track A — adapter only)        │
                                    └──────────────┬───────────────────┘
                                                   │
            ┌──────────────────────────────────────┼──────────────────────────────────────┐
            ▼                                      ▼                                      ▼
   db.get_pending_events()         run_distiller(events, model, cfg)        db.get_context_map(corpus_key)
            │                                      │                                      │
            └──────────────────────┬───────────────┴──────────────────────┬───────────────┘
                                   ▼                                      ▼
                       deterministic_cartographer(distilled, current_map, cycle_n, cfg)
                                                   │
                                                   ▼
                                       CartographerResult
                                                   │
                ┌──────────────────────────────────┼──────────────────────────────────┐
                ▼                                  ▼                                  ▼
    db.write_map(list[MapEntry])     db.append_context_map_event(         db.bump_cycle(corpus_key)
                                       MapEntryEvicted × N)
```

Once Track A is done, Track B layers in:

- **Prompt path** — `app_factory.build_runtime_layer()` reads `list[MapEntry]` and renders an ACDL `ContextMapBlock` into the system prompt.
- **Citation path** — an LLM post-processor scans assistant turns for `[entry:<entry_id>]` markers and emits `MapEntryReferenced`.
- **Cross-corpus path** — a read-only `MultiCorpusContextMap` view that the prompt builder consults for related corpora.
- **Learning path** — an offline job (`harness-poc cartographer calibrate`) that rebalances `priority_weights` from observed reference/eviction rates.

## 3. Track A — Wiring

### 3.1 Skill rewrite

`skills/context-map-materializer/skill.py` becomes an adapter. The full body:

```python
async def execute(ctx: SkillContext, arguments: dict[str, Any]) -> SkillResult:
    corpus_key = str(arguments.get("corpus_key") or "").strip()
    if not corpus_key:
        return SkillResult(status="failed", content="Missing required argument: corpus_key", artifacts={})

    session_id = str(arguments.get("session_id") or "materializer")
    db = ctx.database
    pending = db.get_pending_context_map_events(corpus_key, limit=50)
    if not pending:
        return SkillResult(
            status="success",
            content=f"No pending events for {corpus_key}.",
            artifacts={"corpus_key": corpus_key, "events_processed": 0, "map_changed": False},
        )

    current_map: list[MapEntry] = db.get_context_map(corpus_key) or []
    cycle_n = db.get_and_bump_cycle(corpus_key)
    distiller_model = build_model(ctx.config.distiller.resolved_model(ctx.config.llm))

    events = _events_from_rows(pending, ctx.config.runtime.materializer_max_event_tokens)
    try:
        distilled = await run_distiller(events, distiller_model, ctx.config.distiller)
    except DistillerExhausted as exc:
        return SkillResult(status="failed", content=f"Distiller failed: {exc}", artifacts={})

    result = deterministic_cartographer(distilled, current_map, cycle_n, ctx.config.cartographer)

    for eviction in result.evictions:
        db.append_context_map_event(
            MapEntryEvicted(
                session_id=session_id,
                corpus_key=corpus_key,
                entry_id=eviction.entry_id,
                entry_key=eviction.key,
                section=eviction.section,
                materialization_count=eviction.materialization_count,
                reason=eviction.reason,
            )
        )

    map_changed = _map_changed(current_map, result.new_map)
    token_count = sum(entry.token_estimate for entry in result.new_map)
    db.write_map_and_mark_processed(
        corpus_key,
        result.new_map,
        token_count,
        [row.event_id for row in pending],
    )

    return SkillResult(
        status="success",
        content=f"Materialized {len(pending)} event(s) for {corpus_key}. Map now {token_count} tokens.",
        artifacts={
            "corpus_key": corpus_key,
            "events_processed": len(pending),
            "token_count": token_count,
            "map_changed": map_changed,
            "cycle_n": cycle_n,
        },
    )
```

What disappears:

- `_distiller_messages`, `_cartographer_messages`, `_apply_edits`, `_enforce_budget`, `_detect_promotions`, `_ensure_entry_ids`, `_strip_empty_sections`, `_parse_json`, `_SECTION_PRIORITY`, `_CHARS_PER_TOKEN`.
- The `MapEntryPromoted` derivation. Promotions are an artifact of the old section-table model; the flat `MapEntry` schema has no promotion semantic. The event class itself stays in the registry for backward compat of stored events, but no new ones are emitted.

`_map_changed` compares `[entry.model_dump(exclude={"last_updated"}) for entry in m]` between old and new — `last_updated` would otherwise force every cycle to look changed.

### 3.2 Database migration

Three `BlackboardDatabase` methods change shape:

| Method | Before | After |
|---|---|---|
| `get_context_map(corpus_key)` | `dict[str, dict[str, dict]]` | `list[MapEntry]` |
| `write_map_and_mark_processed(...)` | accepts `dict`, stores JSON | accepts `list[MapEntry]`, stores `[entry.model_dump(mode="json") for entry in map]` |
| `get_pending_context_map_events(...)` | unchanged signature | unchanged; rows already carry `payload` JSON the Distiller consumes |
| `get_cycle(corpus_key) -> int` | n/a | new; read-only sibling of `get_and_bump_cycle`, used by the citation extractor (§4.2) |
| `get_context_maps(corpus_keys) -> dict[str, list[MapEntry]]` | n/a | new; bulk read for cross-corpus enrichment (§4.3). Single SQL `SELECT ... WHERE corpus_key = ANY(...)` |

**Migration strategy.** The `context_maps` table has a `payload` JSON column. Add a sibling `schema_version` column (default `1`). On read:

- `schema_version = 1` → legacy dict format. Translate in-process via `_legacy_to_entries()` (best-effort: each `{section: {key: {entry_id, content, priority_score}}}` becomes a `MapEntry` with `observation_type` inferred from section, `first_seen_cycle = last_seen_cycle = 0`, `materialization_count = 0`, `token_estimate` recomputed via `tiktoken`).
- `schema_version = 2` → new format, deserialize directly.

On write, always write `schema_version = 2`. The translation is lossy (no real cycle history) but acceptable because the legacy maps are short-lived development artifacts — no production data exists today.

A single Alembic migration (`add_schema_version_to_context_maps`) adds the column with default `1`. Existing rows are read once, translated, and rewritten as `schema_version = 2` on the next materializer pass — no batch migration job needed.

### 3.3 Cycle tracking

New table:

```sql
CREATE TABLE context_map_cycles (
  corpus_key TEXT PRIMARY KEY,
  cycle_n INTEGER NOT NULL DEFAULT 0,
  updated_at TIMESTAMP NOT NULL DEFAULT now()
);
```

New method `BlackboardDatabase.get_and_bump_cycle(corpus_key) -> int`:

```python
def get_and_bump_cycle(self, corpus_key: str) -> int:
    # Postgres: INSERT ... ON CONFLICT DO UPDATE RETURNING cycle_n
    # SQLite: SELECT + UPDATE in a transaction
```

Returns the post-increment value, so the first call for a fresh corpus returns `1`. Stored on `MapEntry.first_seen_cycle` / `last_seen_cycle` and quoted in `EvictionRecord.reason` (Part 1 §4.3).

The counter is per `corpus_key`, never reset. Wraparound is not a concern (a million materializations per corpus is years of runtime).

### 3.4 Event emission

Three events flow from a single materializer pass:

1. **`MapEntryInserted`** — one per `MapEntry` whose `key` was not in the prior map (i.e. `first_seen_cycle == cycle_n`). Required by the §4.4 calibration job: without an insertion signal, "entries of this type ever materialized" can only be reconstructed from the current map plus eviction events, which loses entries that were inserted and evicted within the calibration window. This is a **new event class**:

   ```python
   class MapEntryInserted(ContextMapEvent):
       event_type: Literal["map_entry_inserted"] = "map_entry_inserted"
       entry_id: str
       entry_key: str
       section: str
       observation_type: str
       cycle_n: int
   ```

   Add to `CONTEXT_MAP_EVENT_REGISTRY`. Part 1's deprecated `MapEntryPromoted` does **not** serve this purpose — promotions described section changes, not insertions.

2. **`MapEntryEvicted`** — one per `EvictionRecord` in `CartographerResult.evictions`. Already shown in §3.1. The `reason` field carries the Part 1 §4.3 / §4.4 structured string. `materialization_count` is widened on the event class per Part 1 §7.

3. **`MapEntryReferenced`** — deferred to Track B §4.2.

The skill is the only emitter for categories (1) and (2). No event-bus subscriber consumes these today — they exist for telemetry replay and the Track B calibration job.

### 3.5 Config consolidation

Remove from `RuntimeConfig`:

- `materializer_token_budget` — moved to `CartographerConfig.token_budget` in Part 1. No callers remain after §3.1.

Keep in `RuntimeConfig`:

- `materializer_max_event_tokens` — input-side budget for the Distiller; not a Cartographer concern.
- `materializer_freeze_threshold`, `materializer_freeze_seconds` — these gate _when_ to invoke the skill, not what it does. Track A keeps the freeze behavior unchanged; the "changed?" comparison moves from `result.artifacts.get("map_changed")` (skill output) to the same artifact, now derived from `_map_changed()` in §3.1.

Add to `DistillerConfig`:

```python
class DistillerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str | None = None
    max_retries: int = 3
    prompt_template: str = "distiller_v1"

    def resolved_model(self, llm_config: LLMConfig) -> str:
        return self.model or llm_config.primary_model
```

Verify `tiktoken` is in `[project.dependencies]`, not `[project.optional-dependencies.dev]`. If only listed as dev, move it.

### 3.6 Track A acceptance criteria

- `uv run pytest tests/context_map tests/skills/test_context_map_materializer.py` passes.
- A fresh corpus produces a `list[MapEntry]` map with `cycle_n = 1` on first run, `cycle_n = 2` on second.
- A corpus with a `schema_version = 1` row reads, translates, and rewrites as `schema_version = 2` on next pass without data loss of `entry_id` or `content`.
- The materializer emits exactly `len(CartographerResult.evictions)` `MapEntryEvicted` events per pass.
- `RuntimeConfig.materializer_token_budget` is deleted; `ruff check` and `ty check` pass.

## 4. Track B — Capability Extensions

### 4.1 `ContextMapBlock` rendering update

**Problem.** `app_factory._system_message_for()` (lines 368–371, mirrored at 464–466) currently dumps the entire map dict as pretty-printed JSON between `--- Context Map ---` fences. With `list[MapEntry]` this is both uglier (flat list of nine-field objects) and uncited (the agent can't refer to entries unambiguously).

**ACDL clarification.** ACDL is the harness's prompt-specification DSL (see `skills/acdl-syntax/SKILL.md`). It describes prompt structure declaratively; the runtime renders to plain text. The existing `StrFrag ContextMapBlock` in `deverino_react.acdl` already names the slot:

```acdl
StrFrag ContextMapBlock: {
    "--- Context Map ---"
    sys.context_map
    "---"
}
```

The fragment definition stays. What changes is the string that `sys.context_map` resolves to — produced by Python in `app_factory`, not by ACDL.

**Design.** New module `harness_poc/core/context_map/render.py` exports `render_context_map(entries: list[MapEntry], cycle_n: int) -> str` producing a structured plain-text block:

```
cycle: 42
section: parsing_schema
  - [entry:ab12cd34ef56...] (p=0.92) Top-level routes are declared in `harness_poc/cli.py`; subcommands register via Typer.
  - [entry:bc78de90...]    (p=0.88) ...
section: domain_constants
  - [entry:ef56gh78...]    (p=0.71) Default token budget is 1024 (`cartographer.token_budget`).
```

- Entries grouped by `section` in the Part 1 §4 priority order; within section, sorted by `priority` desc, then `entry_id` asc (stable).
- Each line carries the `[entry:<entry_id>]` marker that §4.2 keys off. The marker is plain text — no ACDL semantics required — so the citation contract works regardless of whether the model sees it through ACDL-described prompts or raw strings.
- The `--- Context Map ---` fences stay (the `StrFrag ContextMapBlock` wraps them). `_system_message_for` only changes the body.

System prompt (`harness_poc/system_prompts/SOUL.md` or wherever the tool-use guidance lives) gains one line: _"When you use a fact from the Context Map, cite it inline as `[entry:<id>]` using the bracketed id shown next to the fact. This is how the harness learns which entries earn their tokens."_

**Rollout.** Behind a `harness.yaml` flag `cartographer.prompt_block: structured | json | none` (default `structured`). The `json` mode renders `[entry.model_dump(mode="json") for entry in entries]` (no citation markers, no learning); `none` resolves `sys.context_map` to the empty string so the `StrFrag` produces just the two fence lines. The flag exists so an LLM regression in a given model can be worked around without redeploying.

### 4.2 `MapEntryReferenced` event wiring

**Problem.** Part 1 defined the event; nothing emits it. Without emission, §4.4 calibration has no signal.

**Design.** Two emitter strategies, both supported:

1. **Inline regex post-processor** (default). The seam is `harness_poc/core/processors/llm_worker.py:74` — immediately before `bus.publish_async(LLMTextEmitted(...))`. New helper `_extract_references(content, session_id, database) -> list[MapEntryReferenced]`:

   ```python
   _CITATION_RE = re.compile(r"\[entry:([0-9a-f]{32})\]")  # uuid4().hex form, no dashes

   def _extract_references(content, session_id, database, corpus_key, cycle_n):
       seen: set[str] = set()
       refs: list[MapEntryReferenced] = []
       entries_by_id = {e.entry_id: e for e in database.get_context_map(corpus_key) or []}
       for match in _CITATION_RE.finditer(content):
           entry_id = match.group(1)
           if entry_id in seen:
               continue
           seen.add(entry_id)
           entry = entries_by_id.get(entry_id)
           if entry is None:
               # Marker points at evicted entry; log + count, do not emit.
               continue
           refs.append(MapEntryReferenced(
               session_id=session_id,
               corpus_key=corpus_key,
               entry_id=entry_id,
               entry_key=entry.key,
               section=entry.section,
               cycle_n=cycle_n,
               citation_context=content[max(0, match.start() - 80) : match.end() + 80],
           ))
       return refs
   ```

   Each `ref` is published via `bus.publish_async(ref)` in a loop before the `LLMTextEmitted` publish.

   **Where `corpus_key` and `cycle_n` come from.** `_system_message_for` already resolves the active `corpus_key` from session state. To make it available to `llm_worker.py` without re-deriving, persist it on session start via `database.set_session_state(session_id, "active_corpus_key", corpus_key)` and read it inside the helper with `database.get_session_state(session_id, "active_corpus_key")`. `cycle_n` is read via the new `database.get_cycle(corpus_key)` (§3.2). The match window (160 chars) gives calibration enough context to spot pathological citations without storing whole transcripts.

   Dedup is per-turn (the `seen` set above), keyed on `entry_id`. Multi-corpus emission (the cross-corpus case from §4.3) requires the helper to also check related corpora's maps; that variant ships with §4.3.

2. **Tool-side emission** (future). When a skill explicitly reads a map entry — e.g., a hypothetical `read_context_map_entry(entry_id)` tool — the system tool emits the event directly. Not built in this spec; the regex path is sufficient.

**Failure modes.**

- Markers pointing at evicted entries → log at `debug`, do not emit. Track the count as `map_entry_reference_misses` for §4.4.
- Markers in code blocks → still emitted. Cheap noise; calibration tolerates it.

### 4.3 Cross-corpus insight handling

**Problem.** Today each `corpus_key` has its own isolated map. An insight discovered while working corpus A (e.g., "this monorepo uses Bazel") is invisible when the agent later works on corpus B in the same monorepo.

**Design.** Read-only cross-corpus enrichment at prompt assembly time. Not at materialization time — keeping the Cartographer single-corpus preserves its determinism and avoids cross-corpus dedup, which the Part 1 spec explicitly punted on.

New config:

```yaml
cartographer:
  cross_corpus:
    enabled: false
    related_corpora: # Optional adjacency list; absent = no cross-corpus reads.
      "repo:deverino":
        - "repo:harness_poc"
        - "monorepo:group_one"
    max_cross_entries: 16 # Hard cap on entries injected per cross-corpus pass.
    min_priority: 0.7 # Only inject entries above this priority threshold.
```

At prompt time, `build_runtime_layer()` calls `db.get_context_maps(related_corpora) -> dict[str, list[MapEntry]]` and renders an additional ACDL block:

```
<related_context_maps>
  <map corpus="repo:harness_poc" cycle="17">
    <entry id="..." section="..." priority="0.82">...</entry>
  </map>
</related_context_maps>
```

Entries from related corpora are **never** edited by this corpus's Cartographer. The agent reads them; if it cites one with `[entry:<id>]`, the resulting `MapEntryReferenced` is emitted against the **source** corpus's `corpus_key`, not the active one. The session_id distinguishes cross-corpus usage from native usage in telemetry.

**Out of scope, again.** True cross-corpus dedup — recognizing that two entries in different corpora describe the same fact — requires either embedding similarity or a higher-level "global map" concept. Both are large enough to warrant their own spec.

### 4.4 Adaptive priority-weight learning

**Problem.** The seven `priority_weights` in Part 1 §6 are guesses. Some observation types may earn their slot (frequently referenced, rarely evicted); others may bloat the map.

**Design.** Offline calibration. New CLI: `uv run harness-poc cartographer calibrate [--corpus <key>] [--window-days 14] [--apply | --dry-run]`.

The job:

1. Reads `MapEntryReferenced` and `MapEntryEvicted` events for the window.
2. For each `observation_type`, computes:
   - `ref_rate = references / materialization_count_sum` where `materialization_count_sum` is the sum of `materialization_count` across (a) entries currently in the map of that type and (b) `MapEntryEvicted` events in the window of that type.
   - `survival = 1 - (budget_evictions / insertions)` where `insertions` is the count of `MapEntryInserted` events of that type in the window (see §3.4). `budget_evictions` is the count of `MapEntryEvicted` events of that type whose `reason` starts with `budget@`. Staleness evictions are excluded — they reflect agent disinterest (already captured by `ref_rate`), not budget pressure.
3. Computes a target weight using a fixed, transparent formula (no ML — Principle 1):
   ```
   target_weight = clip(
       base_weight[type] * (0.5 + ref_rate) * (0.5 + survival),
       0.1, 1.0,
   )
   ```
   `base_weight` is the value currently in config; the multiplicative form means a type that is referenced and survives at the corpus average gets its current weight unchanged.
4. In `--dry-run` mode, prints a table:

   ```
   type       current  target  Δ
   dispute    1.00     0.94    -0.06
   schema     0.90     0.97    +0.07
   ...
   ```

5. In `--apply` mode, writes the new weights to `harness.yaml` via the existing `core/config.py` writer, prepending a comment line: `# auto-tuned 2026-05-24 from <N> reference events, <M> eviction events`.

**Guardrails.** Calibration is opt-in (no cron, no auto-apply). The formula is deliberately conservative — single-pass calibration can move a weight by at most a factor of `(1.5 * 1.5) / (0.5 * 0.5) = 9×`, but the clip floors at `0.1` and caps at `1.0` so weights stay in a narrow, comparable range. The job refuses to run with fewer than 50 reference events in the window (configurable via `--min-events`) to avoid tuning on noise.

This is the smallest possible thing that beats the current "tune by feel" status quo and keeps the door open for richer learning later.

## 5. Events (additions in this spec)

One new event class — `MapEntryInserted` (defined in §3.4) — and emission wiring for Part 1's `MapEntryReferenced` / `MapEntryEvicted`. `MapEntryInserted` was discovered during this spec's calibration design (§4.4); without it, "insertions of type X in window W" is not reconstructible from existing events.

`MapEntryPromoted` is **deprecated** but not removed:

- The class stays in `harness_poc/core/events/context_map_events.py` and the registry so historical events deserialize.
- No new emissions after Track A §3.1.
- A docstring note marks it deprecated and points at this spec.

## 6. Testing

| Test file | Coverage |
|---|---|
| `tests/skills/test_context_map_materializer.py` | End-to-end: fake events → adapter skill → mocked Distiller → real Cartographer → DB writes. Asserts evicted-event count, `cycle_n` increment, `map_changed` flag. |
| `tests/storage/test_context_map_migration.py` | `schema_version = 1` row reads as `list[MapEntry]`; round-trips as `schema_version = 2`; `entry_id` preserved; `token_estimate` repopulated. |
| `tests/storage/test_cycle_counter.py` | `get_and_bump_cycle` is monotonic, per-corpus, atomic under concurrent calls (Postgres path uses `ON CONFLICT`). |
| `tests/context_map/test_render.py` | `render_context_map` deterministic across runs; entries grouped/sorted as specified; `[entry:<id>]` marker present for every entry; summaries with newlines collapsed to single line. |
| `tests/processors/test_reference_extraction.py` | Regex finds well-formed markers; ignores malformed; resolves to current map; dedup per turn; cross-corpus markers attribute to source corpus. |
| `tests/context_map/test_cross_corpus.py` | `cross_corpus.enabled = false` injects nothing; with adjacency, injects up to `max_cross_entries`; respects `min_priority`. |
| `tests/cli/test_calibrate.py` | Formula correctness on a fixture event stream; `--dry-run` writes nothing; `--apply` writes a backup; `--min-events` enforcement. |

No live LLM calls; the materializer test uses `pydantic_ai.models.test.TestModel`.

## 7. Migration & rollout

Sequenced to keep `main` green between PRs:

1. **PR 1 — Track A §3.2, §3.3.** Database migration (`schema_version` column + `context_map_cycles` table) + `BlackboardDatabase` method signature changes. No skill change yet — adapter still reads/writes the legacy format via a temporary `_legacy_writer` shim. Lands behind no flag; storage is dual-shape for one PR window.
2. **PR 2 — Track A §3.1, §3.4, §3.5.** Skill rewrite + event emission + config cleanup. Removes the legacy shim. After this PR the engine is live.
3. **PR 3 — Track B §4.1.** ACDL rendering behind `prompt_block: acdl`; default flipped from `json` to `acdl` in a follow-up commit after one week of dogfooding.
4. **PR 4 — Track B §4.2.** Inline regex emitter for `MapEntryReferenced`.
5. **PR 5 — Track B §4.3.** Cross-corpus reads. Off by default.
6. **PR 6 — Track B §4.4.** `cartographer calibrate` CLI. Opt-in only.

PRs 3–6 are independent and can land in any order after PR 2.

## 8. Decisions (resolved open questions)

| # | Question | Decision | Rationale |
|---|---|---|---|
| 1 | Where does `cycle_n` live? | New `context_map_cycles` table | Single source of truth; survives crashes; trivially atomic via `ON CONFLICT` |
| 2 | Do we keep `MapEntryPromoted`? | Deprecate, do not delete | Historical events must still deserialize; flat schema removes the concept |
| 3 | Where does cross-corpus join happen? | Read-only at prompt assembly | Preserves Cartographer determinism; defers true dedup to its own spec |
| 4 | How does the LLM cite entries? | `[entry:<id>]` inline markers | Cheapest contract; matches existing skill citation patterns; regex-extractable |
| 5 | Migrate legacy maps how? | In-place on next materializer pass | No production data to migrate; lossy translation is fine |
| 6 | Auto-apply calibration? | No — opt-in CLI only | Self-modifying configs invite drift; humans review the table |
| 7 | Calibration algorithm? | Multiplicative formula, no ML | Principle 1 (deterministic infra before LLM reasoning) applies to weight tuning too |
| 8 | Cross-corpus reference attribution? | Source corpus's `corpus_key` | Calibration must measure value at the entry's home, not its visitor |
| 9 | "ACDL injection" — what does it mean? | Update the body that `sys.context_map` resolves to in the existing `StrFrag ContextMapBlock` | ACDL is a prompt-spec DSL, not an XML markup language; the fragment slot already exists in `deverino_react.acdl` |
| 10 | How does calibration know "insertions of type X"? | New `MapEntryInserted` event in §3.4 | Cheapest reliable signal; reconstruction from current map + evictions loses short-lived entries |

## 9. References

- `docs/superpowers/specs/2026-05-23-deterministic-cartographer-design.md` (Part 1)
- `docs/superpowers/specs/2026-05-24-cartographer-wiring-implications.md`
- `docs/superpowers/specs/2026-05-20-event-sourced-context-map-design.md`
- `docs/superpowers/specs/2026-07-23-context-map-freeze-derivation-ids.md`
- `harness_poc/core/context_map/` (Part 1 implementation)
- `harness_poc/core/events/context_map_events.py`
- `skills/context-map-materializer/skill.py` (rewritten in §3.1)
- `harness_poc/app_factory.py` (`build_runtime_layer`, `_system_message_for`)
