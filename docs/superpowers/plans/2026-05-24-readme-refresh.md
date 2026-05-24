# Plan: README refresh

**Date**: 2026-05-24
**Status**: proposed
**Target file**: `README.md` (single file)

The README has drifted from the codebase across three commit clusters:
the deterministic-cartographer rewrite (`e90f602`, `2bffee0`), the
auto-observe post-turn hook (`7d721dc`, `16c07f8`), and several smaller
additions (`acdl_inspect`, `inspect_own_context`, ACDL knowledge skills,
new observation types). This plan rewrites the stale sections in place;
section ordering and tone stay the same.

Every edit below is scoped to one location. Apply them in the listed
order — earlier edits don't depend on later ones, but doing them in
order makes the diff easy to review.

---

## Edit 1 — `harness.yaml` example block (README lines 63-87)

**Why**: the example is missing `paths:`, `tui:`, `distiller:`, and
`cartographer:` sections that exist in the real `harness.yaml`, and the
`retrieval:` snippet omits the auto-index fields.

**Action**: replace the entire ```yaml block (lines 63-87) with a block
that mirrors the real `harness.yaml` shape. Use the real file as
ground truth (`/Users/matthijskruger/personal_projects/deverino/harness.yaml`).
Keep the example complete but trim long lists where they don't
add explanatory value (e.g. `auto_index_paths` can show one entry).

**Required fields to include** (copy values verbatim from `harness.yaml`):
- `version: 1.1`
- `project.id`
- `llm.provider`, `llm.model`
- `paths:` block (soul, system_tools, system_skills, project_skills,
  personas, workflows, pipelines)
- `runtime:` block — keep all existing `materializer_*` fields, plus
  `default_container_image`, `container_ttl_seconds`,
  `max_harness_containers`, `chat_history_max_tokens`,
  `chat_history_recent_turns`, `tool_result_max_chars`
- `observability:` block (logfire, logfire_include_content)
- `tui:` block (vim_enabled, vim_initial_mode)
- `retrieval:` block — current README version plus `chunk_size_chars`,
  `chunk_overlap_chars`, `max_feed_workers`, `max_file_bytes`,
  `query_timeout_seconds`, `auto_index_paths`, `auto_index_ignore_paths`
- **NEW** `distiller:` block (model, max_retries, prompt_template)
- **NEW** `cartographer:` block (token_budget, tokenizer_name,
  recency_bonus, recency_cap, staleness_penalty, staleness_floor,
  priority_weights for all 7 observation types)

After the YAML block, add one short paragraph (2 sentences) explaining
that `distiller:` and `cartographer:` configure the two-stage context-map
pipeline — Distiller is LLM, Cartographer is deterministic Python.

---

## Edit 2 — PEEK Context Map section (README lines 154-222)

**Why**: this section is the most stale part of the README. It describes
the Cartographer and Evictor as LLM passes, but commits `e90f602` and
`2bffee0` replaced them with deterministic Python. It also omits the
auto-observe post-turn hook entirely.

**Action**: rewrite the section. Keep the heading `## PEEK Context Map`
and the opening paragraph (lines 155-158) as-is — they still describe
the intent correctly. Replace everything from "The implementation keeps
the PEEK pipeline shape…" (line 160) through the end of the section
(line 222) with the structure below.

### New pipeline diagram

Replace the existing diagram (lines 163-170) with one that names the
deterministic stages:

```text
agent/tool activity
  -> typed context-map events in PostgreSQL
  -> Distiller (LLM)  — extracts observations from event batches
  -> Cartographer (deterministic) — priority queue with budget enforcement
  -> Evictor (deterministic) — removes lowest-priority entries on overflow
  -> compact context_map row, materialized via background poller
  -> next app/session prompt includes the stored map
```

### New "current components" list

Replace the existing bullet list (lines 173-184) with:

- typed Pydantic event models in `harness_poc/core/events/context_map_events.py`
- pipeline schema in `harness_poc/core/context_map/schema.py`
  (`DistillerEntry`, `DistilledBatch`, `MapEntry`, `EvictionRecord`,
  `CartographerResult`)
- PostgreSQL tables `context_map_events` and `context_map`
- LLM-driven `Distiller` in `harness_poc/core/context_map/distiller.py`
  with retry/repair and structured output
- deterministic `Cartographer` in `harness_poc/core/context_map/cartographer.py`
  that scores entries by `priority_weight × recency × (1 − staleness)`
- deterministic Evictor (in the same module) that drops the lowest-priority
  entries when the token budget is exceeded
- `context-map-materializer` project skill that orchestrates one full
  Distiller → Cartographer → Evictor pass for a corpus key
- `MaterializerRunner`, started by the TUI and main async runtime, which
  polls pending corpus keys
- `append_event` system skill for manually appending typed events
- `observe` project skill — emits structured observations with 7 types
  (entity, schema, insight, dispute, boundary, constant, result)
- **automatic post-turn observation extraction**: signal-tool turns
  (e.g. `semble_search`, `read_file`, `search_documents`,
  `consolidate_state`) are summarized by a background classifier and fed
  through `observe` without the agent having to ask. See `pydantic_runtime.py:extract_observations_from_turn`.
- `search_documents` and `search_failed` events from retrieval skills
- prompt injection of the stored context map during app-state creation

### New freeze paragraph

Keep the freeze paragraph (lines 186-190) — it is still accurate.
Re-verify nothing has changed in `MaterializerRunner` before reusing
verbatim; if changed, adjust.

### New map-entry paragraph

Replace lines 192-197 (entry_id / ADD / REPLACE) with a paragraph
describing the new schema:

> Map entries (`MapEntry` in `core/context_map/schema.py`) carry stable
> 8-character `entry_id` values, observation type, summary, source
> event IDs, materialization count, cycle bounds, and a token estimate.
> Priority is recomputed each cycle from configurable
> `priority_weights`, recency bonus, and staleness penalty (see
> `cartographer:` in `harness.yaml`). Evictions are auditable —
> `EvictionRecord` entries record the structured reason.

### New calibration paragraph

After the corpus-key paragraph (lines 200-203), add a new paragraph and
example:

> Priority weights can be calibrated from observed reference/eviction
> rates. The `cartographer calibrate` CLI command reads
> `MapEntryReferenced`, `MapEntryEvicted`, and `MapEntryInserted` events
> from the event log over a configurable window and computes target
> weights deterministically.
>
> ```bash
> # Dry run — print the target weights and deltas
> uv run harness-poc cartographer calibrate --window-days 14
>
> # Apply — write new weights to harness.yaml
> uv run harness-poc cartographer calibrate --apply
> ```

### Keep verbatim

Keep the `append_event` example block (lines 204-214) and the
materializer-invocation example (lines 217-221). Both still work.

---

## Edit 3 — CLI section (README lines 224-264)

**Why**: missing two command groups now wired into the Typer app
(`cartographer`, `acdl`).

**Action**: at the end of the existing CLI fenced block (before line
264's closing ```` ``` ````), add:

```bash
# Cartographer calibration
uv run harness-poc cartographer calibrate --window-days 14
uv run harness-poc cartographer calibrate --apply

# ACDL inspection (parse .acdl spec files)
uv run harness-poc acdl inspect path/to/spec.acdl
```

Verify the `acdl inspect` invocation matches the real command shape by
running `uv run harness-poc acdl --help` before committing.

---

## Edit 4 — Architecture tree (README lines 290-357)

**Why**: missing the `core/context_map/` package (added in `e90f602`),
two new system tools (`acdl_tools.py`, `inspect_context.py`), and the
`core/acdl/` package (referenced by `cli.py:15`).

**Action**: edit the tree in place. Insert lines and leave the rest of
the tree intact. Verify each path exists with `ls` before adding.

Under `core/`, after `events/` and before `execution/`, add:

```
│   ├── acdl/               # ACDL parser and CLI app
│   │   └── cli.py          # `harness-poc acdl …` sub-commands
│   ├── context_map/        # Deterministic cartographer pipeline
│   │   ├── schema.py       # DistillerEntry, MapEntry, EvictionRecord
│   │   ├── distiller.py    # LLM extraction with retry/repair
│   │   ├── cartographer.py # Deterministic priority queue + evictor
│   │   ├── calibrate.py    # priority_weights calibration
│   │   ├── render.py       # Map → prompt-fragment rendering
│   │   ├── sections.py     # Section layout helpers
│   │   └── prompts/        # Distiller prompt templates
```

Inside `system_tools/`, list the actual files (the README currently
shows only the directory). Add a comment line below `system_tools/`:

```
├── system_tools/           # Built-in LLM-callable primitives
│   ├── file_tools.py       # read_file, write_file, patch, search_files
│   ├── container_spawn.py, container_exec.py, container_destroy.py
│   ├── execute_python.py
│   ├── read_memory.py
│   ├── knowledge_tools.py
│   ├── acdl_tools.py       # acdl_inspect
│   └── inspect_context.py  # inspect_own_context
```

Leave `core/runtime/`, `core/storage/`, `core/skills/`, `core/retrieval/`,
`core/observability/`, `core/processors/`, `core/tools/`,
`system_skills/`, `system_prompts/` as they are — they were verified to
still match the codebase.

---

## Edit 5 — Tools and Skills tables (README lines 401-431)

**Why**: missing two tools and one skill; one skill name in the table
needs verification.

**Action — table at lines 401-415**: add three new rows. Place them
where they fit semantically (group with similar tools).

| Name | Purpose |
|---|---|
| `inspect_own_context` | Return the agent's own assembled system prompt for self-inspection |
| `acdl_inspect` | Parse an ACDL spec file and return a structured summary |

Update the existing `observe` row to clarify the 7 types:

| `observe` | Record structural observations (7 types: entity, schema, insight, dispute, boundary, constant, result) for the context map |

**Action — table at lines 418-431**: verify each row still points to a
real skill. Two adjustments:

- Add a row for `acdl-syntax` (knowledge skill, currently in `skills/`):

  | `acdl-syntax` | ACDL grammar quickstart and gotchas |

- Add a row for `acdl-tooling` (knowledge skill, currently in `skills/`):

  | `acdl-tooling` | How to use `acdl_inspect` from inside the agent loop |

- Add a row for `deterministic-cartographer` (knowledge skill):

  | `deterministic-cartographer` | Design rationale for the deterministic Cartographer migration |

Do not list `compact-session` — it is no longer in `skills/`.

---

## Edit 6 — Runtime Model section (README lines 359-385)

**Why**: mostly accurate, but it doesn't mention that the context-map
pipeline is now split between an LLM Distiller and deterministic
Cartographer/Evictor stages. The paragraph at lines 374-380 still says
"the background materializer turns unprocessed events into a compact
map" which is true but underspecified.

**Action**: replace the paragraph at lines 374-380 with:

> The context-map subsystem uses its own event log in the blackboard.
> Tool and skill activity (plus the auto-observe post-turn hook) appends
> typed orientation events. The background materializer runs a two-stage
> pipeline: an LLM Distiller extracts observations into `DistillerEntry`
> records, then a deterministic Python Cartographer scores and evicts
> entries against a token budget. The materialized map is loaded into
> future system prompts. This map is a cache, not a source of truth; if
> materialization fails, events remain unprocessed and are retried on
> the next poll. Stable maps can be temporarily frozen to save Distiller
> LLM calls.

Leave the surrounding paragraphs (event-sourced goal path; GoalRunner)
untouched.

---

## Edit 7 — Testing section (README lines 491-516)

**Why**: minor. The three-layer story is correct, but the directory
layout description undersells the structure. Optional fix.

**Action**: after the three-layer table (line 510), add one sentence:

> Within each layer, tests are grouped by domain — e.g. `tests/unit/`
> includes subdirectories for `context_map/`, `retrieval/`, `runtime/`,
> `skills/`, `processors/`, `repl/`, `event/`, `infra/`.

Adjust the path if the actual layout differs — verify with
`ls tests/`.

---

## Out of scope

The following would be useful but are not part of this refresh:

- A new "Observability" subsection covering the dashboard panel for
  context-map entries (`97b8817`).
- A migration note explaining how to move from old LLM-cartographer
  state to the new schema (likely unnecessary — no users beyond the
  author).
- Diagrams (Mermaid / ASCII) for the auto-observe flow.

---

## Verification checklist

Before committing, run each of these and confirm output:

1. `ls harness_poc/core/context_map/` — confirm the file list in Edit 4
   matches the tree.
2. `ls harness_poc/system_tools/` — confirm Edit 4's tool list.
3. `ls skills/` — confirm Edit 5's skill list (no `compact-session`,
   yes `acdl-syntax`, `acdl-tooling`, `deterministic-cartographer`).
4. `uv run harness-poc --help` — confirm `cartographer` and `acdl`
   command groups are listed.
5. `uv run harness-poc cartographer calibrate --help` — confirm the
   flag names in Edit 2's calibration example (`--window-days`,
   `--apply`/`--dry-run`).
6. `diff <(yq . harness.yaml) <(...your example...)` — sanity-check the
   YAML in Edit 1 against the real config.
7. After editing, run a markdown linter or visual scan to confirm no
   broken fences or duplicate headings.

## Files touched

| File | Change |
|---|---|
| `README.md` | All edits above — single-file change |

## Order of operations

Apply in numbered order (1 → 7). Each edit is independent, but doing
the YAML block first means the architecture and PEEK rewrites can
reference the new config sections without rework. Land as a single
commit titled `docs: refresh README for deterministic cartographer and
auto-observe hook`.
