# Multi-Corpus Context Map: Unblock Front-End Hardcodes

**Date**: 2026-07-25
**Status**: ready

## Problem

The context map backend fully supports multiple corpus keys — the database,
materializer, and cross-corpus rendering all accept and operate on arbitrary
`corpus_key` values. However, the agent-facing front-end is hardcoded to a
single corpus (`deverino:codebase`), making it impossible to use a second
corpus in practice.

The developer wants to add more corpora beyond `deverino:codebase`.
Currently, even if events were manually inserted for a second corpus (and the
materializer would process them correctly), the agent cannot:

- **Observe into** a second corpus — `observe` always writes to `deverino:codebase`
- **See** a second corpus — the system prompt only loads `deverino:codebase`

## Root Cause

Three hardcoded strings, plus a missing tool parameter:

| Location                                          | Line | Current Behaviour                                                                                |
| ------------------------------------------------- | ---- | ------------------------------------------------------------------------------------------------ |
| `harness_poc/app_factory.py`                      | 465  | `corpus_key = f"{identity.config_project_id}:codebase"` — only one map loaded into prompt        |
| `skills/observe/skill.py`                         | 168  | `corpus_key = f"{ctx.config.project_id}:codebase"` — all observations routed to single corpus    |
| `harness_poc/core/processors/llm_worker.py`       | 133  | `active_corpus_key = f"{config.project_id}:codebase"` — reference extraction pins active corpus  |
| `skills/observe/SKILL.md`                         | —    | No `corpus_key` parameter exposed to the agent                                                   |

Additionally, `harness.yaml` has no `cross_corpus` section configured, so even
the cross-corpus enrichment path (`_render_cross_corpus`) is never triggered.

## What Already Works (No Changes Needed)

These components are fully multi-corpus-ready:

| Component                                                                                                                                        | Evidence                                                                                                            |
| ------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------- |
| **Storage** — `get_context_map()`, `get_pending_context_map_events()`, `get_and_bump_cycle()`, `get_context_maps()`, `get_pending_corpus_keys()` | Operate over arbitrary corpus keys (per-key methods take `corpus_key`; enumeration methods return all keys) |
| **Materializer runner** — `_poll_once()`                                                                                                         | Iterates `get_pending_corpus_keys()` and materializes each independently                                            |
| **Materializer skill** — `context-map-materializer`                                                                                              | Takes `corpus_key` argument                                                                                         |
| **Cross-corpus rendering** — `_render_cross_corpus()`                                                                                            | Fetches related corpus maps and injects high-priority entries as read-only                                          |
| **Dashboard** — `fetch_context_map_health()`                                                                                                     | SQL unions across all corpus keys in `context_map` + `context_map_events`                                           |
| **Config model** — `CartographerConfig`                                                                                                          | Has `cross_corpus_enabled`, `cross_corpus_related_corpora`, `cross_corpus_max_entries`, `cross_corpus_min_priority` |
| **Calibrate** — `run_calibration_cycle()`                                                                                                        | Accepts `corpus_key` parameter                                                                                      |

## Fix: Five Files

### 1. `skills/observe/SKILL.md`

Add optional `corpus_key` parameter to the frontmatter. The agent can then
target observations to a specific corpus when relevant, and falls back to
the project default otherwise.

**Add to `parameters.properties`:**

```yaml
corpus_key:
  type: string
  description: >-
    Target corpus for this observation. Defaults to '{project}:codebase'.
    Use when observing facts about a different corpus (e.g.,
    'deverino:dashboard' for dashboard-specific observations).
```

No change to `required` — it stays optional.

### 2. `skills/observe/skill.py`

**Line 168, replace:**

```python
corpus_key = f"{ctx.config.project_id}:codebase"
```

**With:**

```python
corpus_key = (
    str(arguments.get("corpus_key") or "").strip()
    or f"{ctx.config.project_id}:codebase"
)
if ":" not in corpus_key:
    return SkillResult(
        status="failed",
        content=(
            f"Invalid corpus_key {corpus_key!r}: expected 'project:name' form "
            f"(e.g., '{ctx.config.project_id}:dashboard')."
        ),
        artifacts={},
    )
```

The `_build_*` functions already accept `corpus_key` as their second
parameter — no signature changes needed there.

**Validation rationale:** corpus keys throughout the system follow a
`project:name` convention. Silent acceptance of malformed values (typos like
`deverino-dashboard`) would spawn orphan corpora that the materializer
happily produces but no `related_corpora` mapping ever references. A minimal
"must contain a colon" check catches the typo class without overconstraining
naming.

### 3. `harness_poc/app_factory.py`

**Lines 465-467, the current logic:**

```python
corpus_key = f"{identity.config_project_id}:codebase"
context_map = identity.database.get_context_map(corpus_key)
cycle_n = identity.database.get_cycle(corpus_key)
```

This loads only the primary corpus. Cross-corpus enrichment is already wired
at line 475 via `_render_cross_corpus()` but never fires because
`cross_corpus_enabled` defaults to `False` and `related_corpora` is empty.

**Strategy:** Keep the primary corpus as-is (the agent always needs its own
map). Enable cross-corpus injection by adding the `harness.yaml` config
(change 4 below). No code change needed here — the cross-corpus block
at lines 474-476 already reads `config.cartographer.cross_corpus_enabled`
and conditionally calls `_render_cross_corpus()`.

If the user wants the agent to switch between active corpora (not just see
read-only related ones), a follow-up plan should add a configurable primary
corpus key. For now, cross-corpus enrichment is the correct first step.

### 4. `harness_poc/core/processors/llm_worker.py`

**Line 133, currently:**

```python
active_corpus_key = f"{config.project_id}:codebase"
```

This hardcodes which corpus's entries are treated as authoritative when
resolving `[entry:<id>]` markers in assistant output. With cross-corpus
enrichment turned on, references into related corpora still resolve (the
`related_keys` lookup covers them). But entries from any non-related corpus
(e.g., a freshly-bootstrapped one not yet listed under `related_corpora`)
will not be extracted — their markers are silently dropped from reference
events.

**Scope decision:** Leave this hardcode in place for now, but document the
constraint. The primary corpus stays `:codebase`, and any corpus the agent
should be able to cite must be added to `cross_corpus.related_corpora`. A
follow-up plan (paired with the "configurable primary corpus" work above)
should replace this with the resolved primary corpus key.

**Action this plan:** add a code comment at line 133 referencing this plan
and the follow-up gap; do not change behavior.

### 5. `harness.yaml`

Add a `cross_corpus` block to enable related-corpora injection. Example for
two additional corpora (`deverino:dashboard` and `deverino:benchmarks`):

```yaml
cartographer:
  # ... existing keys remain ...
  cross_corpus:
    enabled: true
    related_corpora:
      "deverino:codebase":
        - "deverino:dashboard"
        - "deverino:benchmarks"
    max_cross_entries: 16
    min_priority: 0.7
```

> **YAML gotcha:** the mapping keys under `related_corpora` contain a colon,
> so they **must be quoted**. Without quotes, YAML parses
> `deverino:codebase` as a nested mapping (`{deverino: {codebase: [...]}}`)
> and `_parse_cross_corpus_corpora` silently returns `{}` — the feature
> stays dark with no error.

This tells the system: when the agent's active corpus is `deverino:codebase`,
also inject high-priority entries (≥0.7, up to 16) from `deverino:dashboard`
and `deverino:benchmarks` into the prompt. The injected entries are read-only
(the active corpus's Cartographer never edits them).

## Tests

The plan claims "low risk." That claim must be backed by tests, since the
change introduces a new agent-facing parameter and a config block that is
silently ignored on YAML typos.

**Required:**

1. **Create `tests/skills/test_observe.py`** (no observe-specific test file
   exists today — `grep -rln observe tests/` confirms). Mirror the
   fixture pattern in `tests/skills/test_consolidate_state.py`: it uses the
   `test_config: HarnessConfig` and `db_engine: Engine` conftest fixtures,
   builds `BlackboardDatabase(db_engine)`, starts a session, then drives
   the skill through `SkillRunner.execute_skill`.

   **Sketch:**

   ```python
   from __future__ import annotations

   from sqlalchemy import Engine

   from harness_poc.core.config import HarnessConfig
   from harness_poc.core.skills import SkillRunner
   from harness_poc.core.storage import BlackboardDatabase

   _BASE_ARGS = {
       "observation_type": "entity",
       "summary": "BlackboardDatabase owns all durable state writes",
       "detail": "Centralizing writes here keeps event ordering deterministic.",
   }


   def _run(
       database: BlackboardDatabase,
       config: HarnessConfig,
       session_id: str,
       **overrides: object,
   ):
       runner = SkillRunner(database=database, config=config)
       return runner.execute_skill(
           tool_name="observe",
           arguments={**_BASE_ARGS, **overrides},
           session_id=session_id,
       )


   def test_observe_defaults_to_codebase_corpus(
       test_config: HarnessConfig, db_engine: Engine,
   ) -> None:
       database = BlackboardDatabase(db_engine)
       session_id = database.start_session("test")
       result = _run(database, test_config, session_id)

       assert result.status == "success"
       expected = f"{test_config.project_id}:codebase"
       assert result.artifacts["corpus_key"] == expected
       events = database.get_pending_context_map_events(expected)
       assert len(events) == 1


   def test_observe_routes_to_explicit_corpus(
       test_config: HarnessConfig, db_engine: Engine,
   ) -> None:
       database = BlackboardDatabase(db_engine)
       session_id = database.start_session("test")
       result = _run(
           database, test_config, session_id,
           corpus_key="deverino:dashboard",
       )

       assert result.status == "success"
       assert result.artifacts["corpus_key"] == "deverino:dashboard"
       assert database.get_pending_context_map_events("deverino:dashboard")
       # Default corpus must not receive a stray event.
       assert not database.get_pending_context_map_events(
           f"{test_config.project_id}:codebase",
       )


   def test_observe_rejects_malformed_corpus_key(
       test_config: HarnessConfig, db_engine: Engine,
   ) -> None:
       database = BlackboardDatabase(db_engine)
       session_id = database.start_session("test")
       result = _run(
           database, test_config, session_id,
           corpus_key="deverino-dashboard",  # missing the ':'
       )

       assert result.status == "failed"
       assert "expected 'project:name'" in result.content
       # No event should land in *any* corpus.
       assert not database.get_pending_context_map_events("deverino-dashboard")
       assert not database.get_pending_context_map_events(
           f"{test_config.project_id}:codebase",
       )
   ```

   Notes for the coding agent:
   - The `_BASE_ARGS` dict satisfies the three required SKILL.md fields
     (`observation_type`, `summary`, `detail`); add `corpus_key` via the
     `**overrides` splat.
   - `get_pending_context_map_events(corpus_key)` is the cheapest way to
     confirm the event was routed — it exists at
     `harness_poc/core/storage/database.py:479`. If the project conftest
     doesn't expose `test_config` / `db_engine`, check `tests/conftest.py`
     (the consolidate-state tests rely on them, so they're already wired).

2. **Extend `tests/context_map/test_config.py`** — alongside
   `test_cartographer_config_defaults`, add a case that loads the example
   YAML block from change #5 via `yaml.safe_load` and passes the resulting
   dict to `load_cartographer_config`, asserting:
   - `cross_corpus_enabled is True`
   - `cross_corpus_related_corpora == {"deverino:codebase": ["deverino:dashboard", "deverino:benchmarks"]}`
   - `cross_corpus_max_entries == 16`, `cross_corpus_min_priority == 0.7`

   This is the test that catches the unquoted-key YAML gotcha — the YAML
   input string must be literally the one in change #5 (quoted keys), and
   an inverse case with unquoted keys should assert the
   related-corpora dict comes back **empty** (documenting the silent-failure
   mode so future readers don't accidentally "fix" it without thinking).

## Known Gaps (Out of Scope)

These are limitations of the unblock, intentionally deferred:

- **Agent discoverability.** SKILL.md tells the agent it *can* target a
  non-default corpus, but the agent has no list of which corpora exist or
  are valid. For now the user must seed corpora deliberately; a follow-up
  could expose a `list_corpora` tool or inject the active corpus inventory
  into the system prompt.
- **Active corpus is still `:codebase`.** The agent's primary map is
  hardcoded. Switching primaries (e.g., a session that is "about" the
  dashboard) requires the configurable-primary follow-up referenced in
  change #3.
- **Reference extraction is still `:codebase`-anchored** (change #4).
  Corpora not listed under `cross_corpus.related_corpora` cannot have their
  `[entry:<id>]` markers resolved.

## Bootstrapping a Second Corpus

Once changes 1-2 are in place, the agent can bootstrap a new corpus by
calling `observe` with `corpus_key: "deverino:dashboard"` (or any other
key). The materializer will pick up the pending events on its next poll
cycle and produce a materialized map.

No database migration or schema change is needed — the `context_map` and
`context_map_events` tables are already keyed on `corpus_key`.

## Execution Order & Commits

Suggested atomic commits, in order:

1. `feat(observe): accept optional corpus_key parameter` — changes #1 + #2 +
   new `tests/skills/test_observe.py`. Verify in isolation.
2. `chore(llm_worker): document active_corpus_key hardcode` — change #4
   (comment-only, references this plan).
3. `feat(cartographer): enable cross-corpus enrichment in harness.yaml` —
   change #5 + the `test_config.py` additions.

Change #3 (`app_factory.py`) is no-op code-wise; fold its rationale into
commit 3's message.

## Acceptance / Verification

Before declaring done, run from repo root:

```bash
uv run pytest tests/skills/test_observe.py tests/context_map/test_config.py -v
uv run pytest                                  # full suite, no regressions
uv run ruff check .
uv run ty check
```

Manual smoke (optional but recommended):

```bash
uv run harness-poc                             # start REPL
# In REPL: ask the model to call `observe` with corpus_key="deverino:dashboard"
# Then verify the materializer picks it up:
uv run harness-poc state show project          # sanity check unaffected
# Inspect blackboard for the dashboard map after the next materializer poll.
```

## Risk Assessment

- **Low risk, contingent on tests landing.** The `observe` change adds an
  optional parameter with the existing default — no existing call sites
  change behavior. Verified by the regression test in the Tests section.
- The `harness.yaml` change is opt-in via `cross_corpus.enabled: true`.
  Without it, behavior is identical to current.
- **YAML config typos fail silently.** Unquoted colon-keys under
  `related_corpora` produce `{}` with no error. The config-load test is
  what guards this — do not skip it.
- **Reference extraction lag.** Corpora outside `related_corpora` cannot
  have their entry markers cited by the agent (change #4). For the unblock
  goal this is acceptable; surface it explicitly in the user-facing notes
  for whoever bootstraps a new corpus.
- Cross-corpus entries are injected as read-only markdown — if the
  Cartographer edits or evicts them, those edits are silently discarded
  (the active corpus only persists its own map). This is by design.
- No database changes. No event schema changes. No pipeline changes.
