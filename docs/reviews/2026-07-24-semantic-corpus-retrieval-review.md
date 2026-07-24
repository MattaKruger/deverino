# Semantic Corpus Retrieval — Final Spec-to-Implementation Review

**Date:** 2026-07-24
**Branch:** `feat/semantic-corpus-retrieval` (10 commits, 22 files, +1195/-19)
**Spec:** `specs/20260724-semantic-corpus-retrieval.md`
**Reviewer:** FinalSpecReview agent

---

## Spec-to-Implementation Map

| Spec Section | Implementation | Status | Notes |
|---|---|---|---|
| **Embedding Store** — `context_map_retrieval_embeddings` table (768-dim bge) | `database.py:1107-1206` — `retrieval_ensure_schema()`, `retrieval_is_available()`, `retrieval_upsert_embeddings()`, `retrieval_get_embeddings()` | ✅ Match | Schema matches spec exactly: `vector(768)`, PK `(corpus_key, entry_key)`, `model` default. Called from `__init__` alongside `copt_ensure_schema()`. Gracefully disabled on SQLite. |
| **Post-Materialization Hook** — embed entries after Cartographer writes | `materializer_runner.py:89-112` — `_embed_retrieval_vectors()` | ⚠️ Partial | Runs after `map_changed=True` regardless of mode (correct per spec). But: no DEBUG logging on failure (spec says "Logged at DEBUG level"), loads bge model even on SQLite where upsert is a no-op, double `suppress(Exception)`. |
| **Dynamic System Prompt Decorator** — `@agent.system_prompt(dynamic=True)`, always registered | `pydantic_runtime.py:359-423` — `_cross_corpus_decorator_fn()` + `_register_cross_corpus_decorator()` | ⚠️ Partial | Always registered in `build_primary_agent()` (✓). Reads mode flag from `AgentDeps.retrieval_mode` (✓). But: no exception handling around semantic path — embedder failures crash the agent turn instead of falling back to priority (spec requires auto-fallback). |
| **Mode Selection** — config default + per-session override + auto-fallback | `config.py:151-156`, `cli.py:162-170`, `repl.py:1450-1463` | ⚠️ Partial | Config default works (✓). CLI flag uses env-var intermediary (`HARNESS_CORPUS_RETRIEVAL`) — functional POC shortcut, not true per-session parameter threading. REPL command properly mutates `AgentDeps.retrieval_mode[0]` (✓). CLI flag accepts any string without validation. Auto-fallback in `semantic_retrieve()` handles missing embeddings (✓) but decorator doesn't catch embedder-load failures. |
| **ACDL Accommodation** — cross-corpus excluded from static prompt in both modes | `app_factory.py:517-527`, `deverino_react.acdl:43-47` | ✅ Match | `compose_system_prompt()` no longer calls `_render_cross_corpus()`. Cross-corpus is handled exclusively by the dynamic decorator. ACDL annotation comment added. |
| **Embedder Cleanup** — fix jina/snowflake mismatch | `embedder.py:7-9,77,136-172` | ❌ Regression | Docstring/comments updated to Snowflake (✓). `prompt_name="retrieval.query"` removed from `embed_query()` (✓). But `return DEFAULT_DIM` was deleted from the `dim` property and not replaced — property now returns `None`. |
| **Config** — 6 new `CartographerConfig` fields | `config.py:150-156,240-247` | ⚠️ Partial | All 6 fields added with correct defaults and parsing (✓). But `cross_corpus_retrieval_model` is never wired to `RetrievalEmbedder` — both instantiation sites use the hardcoded default. `_CARTOGRAPHER_KNOWN_KEYS` not updated (spec says it should be). No validation of unknown sub-keys within `cross_corpus` dict. |
| **CLI/REPL** — `--corpus-retrieval` flag + `/corpus-retrieval` command | `cli.py:162-170,200-208`, `repl.py:1443-1463` | ⚠️ Partial | Both implemented (✓). CLI flag doesn't validate values. No test for the REPL command. CLI flag test only checks `--help` output. |
| **Unified Design** — decorator always runs, mode determines ranking | `pydantic_runtime.py:359-423` | ✅ Match | Decorator always registered, mode flag switches between `semantic_retrieve()` and `priority_retrieve()`. No agent reconstruction needed for per-session toggle. |
| **`retrieval_get_entries_by_keys`** (plan step 3b) | Not implemented | ❌ Missing | Plan step 3b specifies a dedicated `retrieval_get_entries_by_keys(corpus_key, entry_keys)` method. Instead, `semantic_retrieve()` fetches all entries via `get_context_map()` and builds a dict — functionally correct but less efficient. |
| **`DbContextMapRetrievalEmbedding`** dataclass (plan step 1b) | `models.py:211-225` | ⚠️ Dead code | Defined per spec but never imported or used anywhere in the codebase. Matches the existing `DbContextMapEmbedding` pattern (which is also only re-exported, never used in logic). |

---

## Findings

### F001 — `TextEmbedder.dim` property returns `None` after embedder cleanup

- **Severity:** Critical
- **Category:** POC Shortcut / Bug
- **Location:** `harness_poc/core/retrieval/embedder.py:75-78`

**Description:**

The embedder cleanup task (commit `cf74116`) removed `return DEFAULT_DIM` from the `dim` property but did not replace it with anything. The property now has only a docstring and a comment:

```python
@property
def dim(self) -> int:
    """Return the embedding dimension (hard-coded for the default model)."""
    # Snowflake/snowflake-arctic-embed-l-v2.0 -> 1024 by default.
```

It implicitly returns `None`. The type annotation says `-> int`. The only consumer is `embed_batch()` at line 142:

```python
if not texts:
    return np.empty((0, self.dim), dtype=np.float32)
```

When called with an empty text list, `self.dim` is `None`, causing `np.empty((0, None), dtype=np.float32)` to raise `TypeError: 'NoneType' object cannot be interpreted as an integer`. In practice, callers currently guard against empty input before calling `embed_batch`, so the crash is latent. The `DEFAULT_DIM = 1024` constant at line 29 is now dead code.

**Recommendation:**

```python
@property
def dim(self) -> int:
    """Return the embedding dimension (hard-coded for the default model)."""
    # Snowflake/snowflake-arctic-embed-l-v2.0 -> 1024 by default.
    return DEFAULT_DIM
```

---

### F002 — Dynamic decorator has no exception handling in the semantic path

- **Severity:** Important
- **Category:** Spec Drift / Missing Error Handling
- **Location:** `harness_poc/core/runtime/pydantic_runtime.py:395-418`

**Description:**

The spec requires auto-fallback: "when semantic mode is active but pgvector is unavailable... Falls back to priority-based ranking for that corpus." The `semantic_retrieve()` function handles missing embeddings (falls back to `_priority_entries` per corpus). But the decorator's semantic path calls `embedder.embed_query(query)` at line 412-413 with no try/except. If the bge model fails to load (network error, missing weights, OOM), the exception propagates to PydanticAI's `Agent.run()`, crashing the entire turn. The spec's auto-fallback guarantee is not upheld for embedder-load failures.

The deterministic path (lines 419-423) has the same issue — any exception from `priority_retrieve` or `render_block` would crash the turn — but those functions are simpler and less likely to fail.

**Recommendation:**

Wrap the semantic path in a try/except that falls back to `priority_retrieve` on any exception, logging at DEBUG:

```python
if mode == "semantic":
    try:
        # ... embed query, semantic_retrieve, render_block ...
        return render_block(entries, mode="semantic")
    except Exception:
        logger.debug("Semantic retrieval failed, falling back to priority", exc_info=True)
        # fall through to deterministic
entries = priority_retrieve(deps.database, deps.config, active_corpus_key)
return render_block(entries, mode="deterministic")
```

---

### F003 — `cross_corpus_retrieval_model` config field is never used

- **Severity:** Important
- **Category:** Spec Drift
- **Location:** `harness_poc/core/context_map/config.py:152` (definition); `harness_poc/core/execution/materializer_runner.py:103`, `harness_poc/core/runtime/pydantic_runtime.py:412` (instantiation sites)

**Description:**

The config field `cross_corpus_retrieval_model` (default `"BAAI/bge-base-en-v1.5"`) is defined and parsed from YAML, but neither instantiation of `RetrievalEmbedder` passes it:

- `materializer_runner.py:103`: `embedder = RetrievalEmbedder()` — uses default
- `pydantic_runtime.py:412`: `embedder = RetrievalEmbedder()` — uses default

The `RetrievalEmbedder.__init__` accepts a `model_name` parameter, so the wiring is trivial. Changing `retrieval_model` in `harness.yaml` has no effect. Additionally, `_BGE_DIM = 768` is hardcoded in `retrieval_embedder.py:23` — if a different model with a different dimensionality were configured, the `dim` property would be wrong and the `vector(768)` column schema wouldn't match.

**Recommendation:**

Pass the configured model name (and ideally derive the dimension from the loaded model rather than hardcoding 768):

```python
# materializer_runner.py
embedder = RetrievalEmbedder(model_name=self._config.cartographer.cross_corpus_retrieval_model)

# pydantic_runtime.py
embedder = RetrievalEmbedder(model_name=cc.cross_corpus_retrieval_model)
```

---

### F004 — `semantic_retrieve()` has no test coverage

- **Severity:** Important
- **Category:** Missing Test
- **Location:** `tests/context_map/test_semantic_retrieval.py` (entire file)

**Description:**

The test file covers `compose_query` (4 tests), `priority_retrieve` (2 tests), and `render_block` (3 tests). The `semantic_retrieve()` function — the core cosine-similarity ranking logic — has zero tests. This is the function that:
- Fetches embeddings from the DB
- Computes cosine similarity against the query vector
- Filters by `min_similarity`, sorts, takes `top_k`
- Falls back to priority when embeddings are missing
- Merges across corpora and caps total

None of this logic is exercised by any test. The decorator test (`test_dynamic_system_prompt.py`) only tests the deterministic path and the disabled path — the semantic path is never invoked.

**Recommendation:**

Add tests that mock `db.retrieval_get_embeddings` and `db.get_context_map` to return controlled embeddings and entries, then verify similarity ranking, filtering, top_k capping, cross-corpus merge, and fallback behavior.

---

### F005 — Materializer hook silently swallows exceptions without DEBUG logging

- **Severity:** Important
- **Category:** Spec Drift / Missing Error Handling
- **Location:** `harness_poc/core/execution/materializer_runner.py:89-112`

**Description:**

The spec states: "Best-effort: if pgvector is unavailable or embedding fails, the materializer still succeeds" and "Logged at DEBUG level." The implementation uses `suppress(Exception)` which silently swallows all exceptions with no logging. The docstring says "failures are logged at DEBUG" but no `logger.debug()` call exists inside the suppress block. Additionally, there is a double `suppress(Exception)` — the outer one in `_materialize()` (line 79) and the inner one in `_embed_retrieval_vectors()` (line 97) — the outer is redundant.

The docstring also says "Only runs when semantic retrieval is enabled" but the code runs regardless of mode (which is correct per the spec — "Runs regardless of mode"). The docstring is misleading.

**Recommendation:**

Replace `suppress(Exception)` with explicit try/except + DEBUG logging, and remove the redundant outer suppress. Fix the docstring.

---

### F006 — `_render_cross_corpus` is now dead code

- **Severity:** Minor
- **Category:** Dead Code
- **Location:** `harness_poc/app_factory.py:536-575`

**Description:**

`_render_cross_corpus()` was the original cross-corpus renderer called from `compose_system_prompt()`. After the patch, `compose_system_prompt()` no longer calls it — the dynamic decorator handles cross-corpus enrichment. The function is still defined (lines 536-575) but has no callers anywhere in the codebase (only referenced in docstrings of `semantic_retrieval.py`). The `_MIN_CROSS_CORPUS_PARTS` constant (line 534) is also only used by this dead function.

**Recommendation:**

Delete `_render_cross_corpus()` and `_MIN_CROSS_CORPUS_PARTS`. The `semantic_retrieval.priority_retrieve()` + `render_block()` pair replaces it.

---

### F007 — `render_block` format differs from `_render_cross_corpus`

- **Severity:** Minor
- **Category:** Spec Drift
- **Location:** `harness_poc/core/context_map/semantic_retrieval.py:159-174`

**Description:**

The spec says "Format matches `_render_cross_corpus()` output for citation compatibility." The citation markers (`[entry:<id>]`) are present in both, so citation resolution works. But the formats differ structurally:

- **Original** `_render_cross_corpus`: groups entries by corpus with `## {corpus_key} (cycle {cycle})` headers
- **New** `render_block`: flat list, no corpus headers, no cycle numbers

The model loses corpus provenance context — it can't tell which corpus an entry came from. This could affect the model's ability to reason about which persona observed what.

**Recommendation:**

Either add per-corpus grouping to `render_block` to match the original format, or update the spec to document the intentional format change.

---

### F008 — CLI `--corpus-retrieval` flag accepts any string without validation

- **Severity:** Minor
- **Category:** Hardening
- **Location:** `harness_poc/cli.py:168-170,207-209`

**Description:**

The CLI flag sets `os.environ["HARNESS_CORPUS_RETRIEVAL"] = corpus_retrieval` for any non-empty string. If a user passes `--corpus-retrieval foo`, it sets `retrieval_mode=["foo"]`. The decorator checks `if mode == "semantic"` — anything else silently falls through to deterministic. The REPL command validates (`if mode not in ("semantic", "deterministic")`), but the CLI does not. An invalid value gives no feedback.

**Recommendation:**

Validate the CLI flag value and error on invalid input, or at minimum warn:

```python
if corpus_retrieval and corpus_retrieval not in ("semantic", "deterministic"):
    raise typer.BadParameter("Must be 'semantic' or 'deterministic'", param_hint="--corpus-retrieval")
```

---

### F009 — No test for `/corpus-retrieval` REPL command

- **Severity:** Minor
- **Category:** Missing Test
- **Location:** `tests/` (no matching test file)

**Description:**

The `handle_corpus_retrieval_command()` function (`repl.py:1450-1463`) is untested. There are no tests for: setting a valid mode, querying the current mode, rejecting an invalid mode, or the command detection logic (`_is_corpus_retrieval_command`). The command directly mutates `app_state.runtime.pydantic_runtime.deps.retrieval_mode[0]` — if `deps` is `None` or `pydantic_runtime` is not initialized, this would raise an `AttributeError`.

**Recommendation:**

Add tests that exercise the command through `handle_repl_input` or directly through `handle_corpus_retrieval_command` with a mock `AppState`.

---

### F010 — `DbContextMapRetrievalEmbedding` dataclass is dead code

- **Severity:** Minor
- **Category:** Dead Code
- **Location:** `harness_poc/core/storage/models.py:211-225`

**Description:**

The `DbContextMapRetrievalEmbedding` dataclass is defined per spec step 1b but never imported or used anywhere in the codebase. The retrieval embedding table is created via raw SQL and accessed via raw SQL queries with manual serialization/deserialization (using `_serialize_embedding` / `_deserialize_embedding` module functions). The dataclass serves no purpose. (Note: the existing `DbContextMapEmbedding` for the CopT gate follows the same pattern — defined but not used in logic, only re-exported from `__init__.py`.)

**Recommendation:**

Either remove it, or add it to `storage/__init__.py` re-exports for consistency with `DbContextMapEmbedding`. Low priority either way.

---

### F011 — Materializer hook loads bge model even when pgvector is unavailable

- **Severity:** Minor
- **Category:** Performance / POC Shortcut
- **Location:** `harness_poc/core/execution/materializer_runner.py:97-110`

**Description:**

`_embed_retrieval_vectors()` does not check `self._db.retrieval_is_available()` before embedding. On SQLite (or PostgreSQL without pgvector), it:
1. Fetches map entries
2. Instantiates `RetrievalEmbedder()` and calls `embed_entries()` — this loads the bge model (~400MB) and computes embeddings
3. Calls `retrieval_upsert_embeddings()` — which is a no-op (returns early because `retrieval_is_available()` is `False`)

The model load and embedding computation are wasted work. The spec says the hook is "best-effort" and "Runs regardless of mode — embeddings are needed for semantic mode and harmless when deterministic." But running on SQLite where embeddings can't be stored is not "harmless" — it wastes CPU and memory.

**Recommendation:**

Add an early return when retrieval is not available:

```python
def _embed_retrieval_vectors(self, corpus_key: str) -> None:
    if not self._db.retrieval_is_available():
        return
    # ... rest of method ...
```

---

### F012 — No validation of unknown sub-keys within `cross_corpus` config

- **Severity:** Minor
- **Category:** Hardening
- **Location:** `harness_poc/core/context_map/config.py:237-247`

**Description:**

`load_cartographer_config()` validates top-level keys against `_CARTOGRAPHER_KNOWN_KEYS`, but the `cross_corpus` sub-dict is parsed with `.get()` calls that silently ignore unknown keys. A typo like `retrival: semantic` (missing 'e') or `semantic_topk: 5` (missing underscore) would be silently ignored, falling back to defaults with no warning. The spec says the new fields should be "added to `_CARTOGRAPHER_KNOWN_KEYS`" — they weren't, and since they're nested under `cross_corpus`, adding them to the top-level set wouldn't help. A sub-key validation set is needed.

**Recommendation:**

Add a `_CROSS_CORPUS_KNOWN_KEYS` frozenset and validate `cc_dict` against it, warning or erroring on unknown keys.

---

### F013 — Env-var intermediary for CLI flag is a POC shortcut

- **Severity:** Minor
- **Category:** POC Shortcut
- **Location:** `harness_poc/cli.py:168-170` (sets env var); `harness_poc/app_factory.py:447-449` (reads env var)

**Description:**

The `--corpus-retrieval` CLI flag sets `os.environ["HARNESS_CORPUS_RETRIEVAL"]`, which `build_runtime_layer()` reads via `os.environ.get()`. This works for a single-process POC but has drawbacks:
- The env var persists for the process lifetime — if the process is reused, the flag leaks to subsequent sessions.
- It's global mutable state, not thread-safe.
- It bypasses the config layer — the config default and the env var override are resolved in different places.

The spec says "Per-session override — `--corpus-retrieval` CLI flag... Updates a mutable runtime flag on `AgentDeps`." The env var approach doesn't update `AgentDeps` directly — it sets the *initial* value of `retrieval_mode` during `build_runtime()`. Runtime toggling is only possible via the REPL command (which does mutate `AgentDeps.retrieval_mode[0]` directly).

**Recommendation:**

Thread `retrieval_mode` as a parameter through `_new_app_state` → `build_app_state` → `build_runtime_layer` → `build_runtime`, instead of using an env var. This is a larger refactor but eliminates the global-state shortcut.

---

### F014 — `test_corpus_retrieval_flag_accepted` is a no-op assertion

- **Severity:** Minor
- **Category:** Missing Test
- **Location:** `tests/cli/test_corpus_flag.py:25-30`

**Description:**

The test invokes `app, ["--help"]` and asserts `"--corpus-retrieval" in result.output`. This verifies the flag appears in help text but does not test that the flag is actually parsed, that it sets the env var, or that the mode reaches `AgentDeps`. The test name suggests the flag is "accepted" but it only checks documentation.

**Recommendation:**

Add a test that invokes the app with `--corpus-retrieval semantic` and verifies `os.environ["HARNESS_CORPUS_RETRIEVAL"]` is set (or better, after the env-var shortcut is removed, that the mode reaches the runtime).

---

### F015 — Decorator test title claims "in both modes" but only tests deterministic

- **Severity:** Minor
- **Category:** Missing Test
- **Location:** `tests/context_map/test_cross_corpus.py:176-243`

**Description:**

The test `test_compose_system_prompt_excludes_cross_corpus_in_both_modes` verifies that `compose_system_prompt()` excludes cross-corpus from the static prompt. The name says "in both modes" but the test only constructs one config with the default `cross_corpus_retrieval="deterministic"`. It never tests with `cross_corpus_retrieval="semantic"`. The static prompt exclusion should hold in both modes (it does — `compose_system_prompt` doesn't check the mode at all), but the test doesn't verify this.

**Recommendation:**

Either rename the test to drop "in both modes", or parametrize it to test both `deterministic` and `semantic` modes.

---

### F016 — Retrieval embedder tests require real model download

- **Severity:** Minor
- **Category:** Missing Test / POC Shortcut
- **Location:** `tests/context_map/test_retrieval_embedder.py:16-40`

**Description:**

`TestRetrievalEmbedder` tests (`test_embed_query_returns_768_dim_vector`, `test_embed_entries_returns_correct_count`, `test_similar_queries_have_high_cosine_similarity`) instantiate `RetrievalEmbedder()` and call real embedding methods. These tests load the actual `BAAI/bge-base-en-v1.5` model (~400MB download). They will fail in any CI environment without the model cached or without network access. They are integration tests masquerading as unit tests.

**Recommendation:**

Mark these tests with `@pytest.mark.slow` or `@pytest.mark.integration`, or mock the `TextEmbedder` to avoid real model loads in the default test suite.

---

### F017 — `retrieval_get_entries_by_keys` (plan step 3b) not implemented

- **Severity:** Info
- **Category:** Spec Drift
- **Location:** `harness_poc/core/storage/database.py` (missing); `harness_poc/core/context_map/semantic_retrieval.py:98-104` (workaround)

**Description:**

The implementation plan step 3b specifies adding `retrieval_get_entries_by_keys(corpus_key, entry_keys) -> list[MapEntry]` to fetch only the selected entries. Instead, `semantic_retrieve()` fetches all entries for each corpus via `db.get_context_map(corpus_key)` and builds a lookup dict. For small corpora (<20 entries) this is negligible, but it's a deviation from the plan and fetches more data than necessary.

**Recommendation:**

Implement the dedicated method for efficiency, or document the deviation as acceptable for the POC.

---

## Hardening Priorities

Ranked by impact on moving from POC to stable:

| Priority | Finding | Effort | Rationale |
|---|---|---|---|
| **1** | F001 — Fix `dim` property returning `None` | Trivial (1 line) | Latent crash in `embed_batch` empty-input path. One-line fix. Blocks any caller that passes empty lists. |
| **2** | F002 — Add exception handling to decorator semantic path | Small | Without this, any embedder failure (model load, network, OOM) crashes the agent turn. The spec's auto-fallback guarantee is unmet. |
| **3** | F003 — Wire `cross_corpus_retrieval_model` to `RetrievalEmbedder` | Small | Config field exists but is dead. Users changing the model in YAML get no effect. Two-line fix at the instantiation sites. |
| **4** | F005 — Replace `suppress(Exception)` with try/except + DEBUG logging | Small | Spec requires DEBUG logging on fallback. Silent failure makes debugging impossible. Also fix misleading docstring and remove redundant double-suppress. |
| **5** | F004 — Add tests for `semantic_retrieve()` | Medium | The core ranking logic is completely untested. Any regression in cosine similarity, filtering, or fallback would go undetected. |
| **6** | F011 — Skip embedding when pgvector unavailable | Trivial | Prevents wasteful model load on SQLite. One-line guard. |
| **7** | F007 — Align `render_block` format with `_render_cross_corpus` | Small | Corpus provenance is lost in the new flat format. Either restore grouping or document the change. |
| **8** | F008 — Validate CLI `--corpus-retrieval` flag value | Small | Invalid values silently fall through to deterministic with no feedback. |
| **9** | F006 — Delete dead `_render_cross_corpus` | Trivial | Dead code confuses future maintainers about which renderer is active. |
| **10** | F009 — Add tests for `/corpus-retrieval` REPL command | Small | The runtime toggle path is untested. |
| **11** | F013 — Replace env-var shortcut with parameter threading | Medium | Eliminates global mutable state. Larger refactor but needed for multi-session correctness. |
| **12** | F012 — Validate `cross_corpus` sub-keys | Small | Prevents silent typos in config. |
| **13** | F015 — Fix misleading test name or parametrize | Trivial | Test claims "both modes" but tests one. |
| **14** | F016 — Mark integration tests | Trivial | Prevents CI failures from model downloads. |
| **15** | F010 — Remove or re-export `DbContextMapRetrievalEmbedding` | Trivial | Dead code cleanup. |
| **16** | F014 — Strengthen CLI flag test | Small | Current test is a no-op assertion. |
| **17** | F017 — Implement `retrieval_get_entries_by_keys` or document deviation | Small | Plan deviation; acceptable for POC. |

---

## Summary

The implementation closely follows the spec's architecture: separate 768-dim embedding table, post-materialization hook, dynamic decorator with mode switching, and ACDL accommodation. The core design is sound and the unified decorator approach works as specified.

**One critical regression** (F001: `dim` returns `None`) was introduced by the embedder cleanup task — a one-line deletion that wasn't replaced. **Two important gaps** remain: the decorator lacks exception handling for the semantic path (F002), and the `cross_corpus_retrieval_model` config field is dead (F003). The `semantic_retrieve()` function — the feature's core logic — has no test coverage (F004).

The remaining findings are minor: dead code, format drift, missing tests for REPL/CLI paths, and POC shortcuts (env-var intermediary, no config sub-key validation). None block a POC merge, but F001–F005 should be fixed before any production use.
