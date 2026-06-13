# Plan: Auto-observe post-turn hook — part 2 (review fixes)

**Date**: 2026-05-24
**Status**: proposed
**Predecessor**: `2026-05-24-auto-observe-post-turn-hook.md` (implemented in 7d721dc)

This plan addresses concrete issues found during review of the part 1
commit. Each fix is scoped tightly — no new features, no refactors
beyond what the fix requires.

## Fix 1 — Produce a real `detail` field (signal-quality bug)

**Problem**: `extract_observations_from_turn` passes `entry.summary` as
both `summary` and `detail` to the `observe` skill
(`pydantic_runtime.py:818-822`). `DistillerEntry` has no `detail` field,
so the classifier never produces one. The `observe` SKILL.md requires
`detail` to explain *why this matters* — the current implementation
strips that entire dimension of signal and pollutes the context map with
duplicate text in two fields.

**Approach**: define a local pydantic model dedicated to this hook —
`AutoObserveEntry` / `AutoObserveBatch` — with both `summary` and
`detail` as required fields. Update the classifier prompt to populate
both. Keep it local to `pydantic_runtime.py`; do not modify the
shared `DistilledBatch` schema (the cartographer's distiller has its
own contract).

**Files**:
- `harness_poc/core/runtime/pydantic_runtime.py` — add local
  `AutoObserveBatch` model, update prompt to request `detail`, parse
  against the new model, pass `entry.detail` through to `observe`.

**Prompt addition** (insert into the schema block):
```
"detail": "2-3 sentences explaining why this observation matters —
 what would the agent do differently knowing this, or what would go
 wrong without it"
```

**Verification**: extend tests in fix 3 to assert that `detail` is
distinct from `summary` and is forwarded to the `observe` skill call.

---

## Fix 2 — Resolve the unused `on_skill_completed` callback

**Problem**: `SkillRunner.execute_skill` gained an
`on_skill_completed` parameter (skill_runner.py:135, invoked at L233),
but no caller in the part 1 commit passes it. The chat path inspects
`response.messages` post-hoc; the GoalRunner reads `result.content`
directly. The plan claimed this would be the single extension point —
in practice it is dead code.

**Decision**: **remove** the parameter for now. Rationale:

- The chat path needs the *aggregated* turn (multiple tool results in
  one classifier call); a per-skill callback is the wrong granularity.
- The goal path also aggregates per run, not per skill.
- Keeping unused extension points invites future drift and obscures
  the actual extension contract.

If a future feature needs per-skill interception (approach C from the
original plan), the parameter can be re-added at that time without
migration cost — the call sites do not depend on its presence.

**Files**:
- `harness_poc/core/skills/skill_runner.py` — remove the parameter
  and the `if on_skill_completed is not None:` block; drop the
  `PLR0915` noqa if no longer needed.

**Verification**: existing skill_runner tests must still pass; no
external caller references the removed parameter (verified by
`grep -r on_skill_completed harness_poc/ tests/`).

---

## Fix 3 — Add tests for the new code paths

**Problem**: part 1 added no tests. The filter, content builder,
JSON-parse failure handling, and code-fence stripping are all
untested.

**Scope** (pure-function tests only — no live LLM):

**File**: `tests/test_auto_observe_hook.py` (new)

| Test | What it pins down |
|---|---|
| `test_turn_has_signal_tools_true` | A `ModelRequest` with a `ToolReturnPart(tool_name="semble_search")` returns `True` |
| `test_turn_has_signal_tools_false_for_non_signal` | A turn with only `read_memory` returns `False` |
| `test_turn_has_signal_tools_empty` | Empty message list returns `False` |
| `test_build_turn_content_includes_tool_output` | Returned string contains `[tool: semble_search]` and the truncated content |
| `test_build_turn_content_appends_final_text` | `response.content` appears as `[agent final] ...` |
| `test_extract_observations_skips_test_model` | When `is_live_model(model)` is `False`, no `observe` calls are made |
| `test_extract_observations_handles_code_fences` | Classifier output wrapped in ```` ```json ... ``` ```` is parsed correctly |
| `test_extract_observations_swallows_parse_error` | Non-JSON classifier output logs but does not raise |
| `test_extract_observations_forwards_detail` | Successful parse calls `skill_runner.execute_skill("observe", …)` with `detail != summary` |
| `test_extract_observations_empty_entries_noop` | `{"entries": []}` returns without calling `observe` |

The `extract_observations_*` tests stub `chat_text` via
`monkeypatch.setattr` on the module, and assert against a mock
`SkillRunner` (using `unittest.mock.MagicMock`).

**Files**:
- `tests/test_auto_observe_hook.py` — new file.

**Verification**: `uv run pytest tests/test_auto_observe_hook.py`
passes; `uv run ruff check tests/test_auto_observe_hook.py` clean.

---

## Out of scope (deferred)

The following review findings are real but deliberately deferred to
keep this plan tight. Each is captured here so they aren't lost.

- **Prompt-schema drift** — the classifier prompt hardcodes the 7
  `observation_type` values. A future fix could derive the prompt
  fragment from `ObservationType` at import time. Low urgency; the
  enum changes rarely.
- **Per-thread `build_model()`** — cheap today, but a single
  long-lived model on `AppState` would be cleaner. Defer until profiling
  shows it matters.
- **Artifacts dropped in GoalRunner** — `result.artifacts` often hold
  structured data (file lists, paths) that would enrich the classifier
  input. Defer until v1 produces enough observations to evaluate signal
  quality.
- **Daemon-thread shutdown** — DB writes from a daemon thread can be
  cut at process exit. Mitigation (a join with timeout on shutdown) is
  small but touches AppState lifecycle; defer.

## Files touched (summary)

| File | Change |
|---|---|
| `harness_poc/core/runtime/pydantic_runtime.py` | Add `AutoObserveBatch` model, expand prompt to request `detail`, forward `entry.detail` to `observe` |
| `harness_poc/core/skills/skill_runner.py` | Remove unused `on_skill_completed` parameter and invocation block |
| `tests/test_auto_observe_hook.py` | New — 10 tests covering filter, content builder, and extractor behavior |

## Order of operations

1. Fix 2 first (smallest, mechanical removal — keeps surface area
   contracting before we add new code).
2. Fix 1 (adds the local model + prompt change).
3. Fix 3 (tests target the post-fix behavior; writing them last avoids
   churn).

Each step lands as its own commit.
