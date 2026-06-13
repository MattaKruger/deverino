# Deferred Refactors — Multi-Corpus Gap Closure Review

Source: code review of commits `32c366f..03389cc` (multi-corpus gap closure).
Date: 2026-05-24.

Three review agents (reuse / quality / efficiency) flagged the issues below.
Each was deferred from the inline fix pass because the scope or risk exceeded
"medium effort" — they're recorded here so a future refactor can pick them up
without re-running the review.

---

## 1. Duplicated system-prompt assembly in `app_factory.py`

**Files:** `harness_poc/app_factory.py` lines ~370–514
**Functions:** `build_runtime_layer`, `_system_message_for`

Both functions independently:

1. Read `config.paths.soul`
2. Call `ensure_project_state` / `ensure_session_state`
3. Resolve `corpus_key` via `get_session_corpus_key(..., default=f"{project_id}:codebase")`
4. Fetch `get_context_map(corpus_key)` and `get_cycle(corpus_key)`
5. Build the `--- Context Map ---\n{map_body}{cross_body}\n---{inventory}` block
6. Join with `"\n\n".join(filter(None, [system_prompt, state_context, context_map_block or None]))`

The only difference is the return type (`Runtime` vs `Message`-dict).

**Verified pre-existing:** the duplication was present in `bf59c24`
(before this plan). This plan added `_render_corpus_inventory(...)` to both
sites and propagated `get_session_corpus_key` into both — reinforcing the
duplication but not introducing it.

**Why deferred:** untangling requires deciding the new shared API surface
(is the helper `_assemble_full_system_prompt(identity, config) -> str` or
something richer that returns the `Message` directly?). Out of scope for a
review pass.

**Suggested refactor:** extract `_assemble_full_system_prompt(identity,
config) -> str` and have `_system_message_for` wrap its output in
`{"role": "system", "content": ...}`. Bonus: `_system_message_for` could
read the already-assembled prompt out of
`runtime.pydantic_runtime.agent._system_prompts` (which `build_runtime_layer`
already populates) — collapsing the duplicate DB reads at startup as well.

---

## 2. Duplicated CLI entrypoint declarations

**Files:** `harness_poc/cli.py` lines ~115–178
**Functions:** `main_callback`, `repl`

Both declare identical `--resume`, `--resume-last`, `--corpus` options with
identical `Annotated` types and help strings, and both bodies call
`_validate_corpus` → `_new_app_state` → `run_repl`. `main_callback` only
adds an `if ctx.invoked_subcommand is not None: return` guard.

**Verified pre-existing:** present in `bf59c24` with just `--resume`/
`--resume-last`. This plan added `--corpus` to both, doubling the new
declaration.

**Why deferred:** typer's `Annotated` argument introspection makes shared
option declarations awkward — there is no clean "decorator inheritance"
pattern. Worth its own focused refactor.

**Suggested refactor:** define the three options once as module-level
`Annotated` aliases, then reference them in both function signatures. Or
make `repl` a thin wrapper that delegates to `main_callback` after option
parsing.

---

## 3. `CartographerConfig.prompt_block` is stringly-typed

**Files:** `harness_poc/core/context_map/config.py:63`,
`harness_poc/app_factory.py` (compared at `!= "none"` in two places)

`prompt_block` is `str` with an inline comment naming the three legal
values (`"structured"`, `"json"`, `"none"`). `load_cartographer_config` does
not validate the parsed value, so a typo silently passes through and the
`!= "none"` check downstream falls into the "render" branch unexpectedly.

**Verified pre-existing:** introduced in `e90f602` (initial Deterministic
Cartographer commit), not by this plan.

**Why deferred:** turning this into a `Literal["structured", "json", "none"]`
or an `enum.StrEnum` requires updating the YAML loader, every consumer, and
the corresponding tests. Out of scope for a review pass.

**Suggested refactor:** introduce `PromptBlockMode = Literal["structured",
"json", "none"]` in `config.py`, validate the raw value in
`load_cartographer_config`, and update consumers to compare against the
literal type (or the enum members).

---

## 4. `_extract_references` re-queries `get_all_corpus_keys` per LLM turn

**File:** `harness_poc/core/processors/llm_worker.py` lines 120–143

When `cross_corpus_auto_discover` is enabled, `_extract_references` calls
`database.get_all_corpus_keys()` (two SELECTs internally) every time the LLM
emits a response.

**Re-checked, not as bad as flagged:** the efficiency agent described this
as "per chunk" — it is actually per `result.content` returned from
`llm_runtime.run_text(...)`, i.e. once per complete LLM turn, not per
streaming token. The cost is 2 cheap DB queries per turn against an
already-warm connection.

**Why deferred:** to remove it cleanly we'd want a turn-scoped cache
(memoize for the lifetime of one `run_llm_worker` iteration) or to lift the
corpus-key resolution into the LLM worker and pass it in. Either approach
touches the worker's signature and a handful of tests. Not justified at the
current call frequency.

**Suggested refactor (only if profiling shows it matters):** memoize the
corpus-key list on the `BlackboardDatabase` with explicit invalidation on
`append_context_map_event` / `write_map_and_mark_processed`.

---

## 5. Default corpus-key string `f"{project_id}:codebase"` scattered

**Sites (5+):**
- `harness_poc/app_factory.py` (two places, lines ~376, ~484)
- `harness_poc/core/processors/llm_worker.py:134`
- `skills/observe/skill.py:170`
- `skills/search_documents/skill.py` (two places)
- `harness_poc/cli.py` (one place)

Same `f"{...:codebase"` literal repeated across the codebase. No constant or
helper. Flagged by the reuse agent as the cleanest cross-cutting cleanup
opportunity.

**Why deferred:** trivial mechanically, but touches 5+ files across the
runtime and skills boundary — better as its own focused commit so the diff
is obvious to reviewers.

**Suggested refactor:** add `default_corpus_key(project_id: str) -> str` to
either `core/storage/database.py` or `core/context_map/config.py`, and
replace every f-string with a call.

---

## 6. `_render_cross_corpus` N+1 `get_cycle` calls

**File:** `harness_poc/app_factory.py` lines 544–547

For each corpus in `db.get_context_maps(related)`, the rendering loop calls
`db.get_cycle(corpus_key)` individually. With N related corpora this is N
queries — same shape as the `_list_corpora` N+1 that *was* fixed.

**Why deferred:** there is no batch `get_cycles(keys)` method yet. Adding
one is a small DB change, but the call site only fires at startup (system
prompt assembly), so the per-corpus cost is paid once per session — not a
hot path. Pre-existing in `2bffee0`; this plan only added the `inventory`
sibling.

**Suggested refactor:** add `BlackboardDatabase.get_cycles(keys: list[str])
-> dict[str, int]` and use it here and in `_list_corpora` (which still has
the same N+1 for cycle, even after the context-map batch fix).

---

## Quick wins already applied (for reference)

These were fixed inline during the review pass — listed here so a future
reader doesn't re-flag them:

- `config.py`: collapsed `_parse_cross_corpus_{bool,int,float}` into inline
  expressions in `load_cartographer_config`.
- `corpus_tools.py`: replaced N+1 `get_context_map` loop with a single
  `get_context_maps` batch.
- `llm_worker.py` + `app_factory.py`: dropped "Track B §4.2/§4.3" plan
  references from production comments.
- `skills/observe/skill.py`: simplified `_guess_entity_type` redundant
  `(keyword, keyword)` tuple list to a flat keyword tuple.
