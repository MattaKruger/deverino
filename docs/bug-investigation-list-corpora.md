# Bug Investigation: `list_corpora` — Missing `database` Argument

**Date:** 2026-05-24
**Status:** Confirmed real bug (not false positive)
**Severity:** High — tool is completely broken when invoked via LLM tool call

## Summary

The `list_corpora` system tool crashes with `TypeError: _list_corpora() missing 1
required positional argument: 'database'` when the LLM calls it through the
`ToolRunner`. The tool's tests pass only because they bypass `ToolRunner`
entirely and call the handler directly with a manually constructed database.

## Investigation Methodology

This section documents the step-by-step approach used to trace the bug from
symptom to root cause. The method generalizes to other tool-invocation bugs.

### Phase 1: Locate the Tool's Source of Truth

Start with the failing tool name. Search for its definition across three layers:

1. **Handler function** — the Python callable registered as the tool's handler
2. **Registration call** — the `_register(...)` call that wires the handler into
   the tool registry
3. **Test file** — the pytest file that exercises the handler

```
grep: list_corpora
→ deverino/harness_poc/system_tools/corpus_tools.py   (handler + registration)
→ deverino/tests/system_tools/test_list_corpora.py     (tests)
→ deverino/docs/superpowers/plans/...                  (design docs)
```

Read the handler signature and registration schema. Note any discrepancy
between the handler's required parameters and the JSON Schema `parameters`
block sent to the LLM.

**Finding:** Handler requires `database: BlackboardDatabase` (positional,
no default), but the JSON Schema declares `"properties": {}` — meaning the LLM
will never send a `database` argument.

### Phase 2: Trace the Execution Path

The handler is not called directly. It's called through `ToolRunner.execute_tool()`.
Read that method to understand how arguments flow from LLM → tool runner → handler.

```
read_file: deverino/harness_poc/core/tools/tool_runner.py:143-210
```

Key observation in `execute_tool`:

```python
if _accepts_context(handler):
    ctx = ToolContext(...)
    result = self._execute_handler(tool_name, handler, token, ctx, **kwargs)
else:
    result = self._execute_handler(tool_name, handler, token, **kwargs)
```

The `_accepts_context` gate determines whether a `ToolContext` is injected as
the first positional argument. If it returns `False`, the handler is called
with only the keyword arguments from the LLM.

### Phase 3: Inspect the Gate Logic

Read `_accepts_context` to understand what it checks:

```
read_file: deverino/harness_poc/core/tools/tool_runner.py:323-341
```

```python
def _accepts_context(handler: object) -> bool:
    sig = inspect.signature(handler)
    first = list(sig.parameters.values())[0]
    ann = first.annotation
    return getattr(ann, "__name__", "") == "ToolContext"
```

**Finding:** The gate checks whether the first parameter is annotated as
`ToolContext`. `_list_corpora`'s first parameter is `BlackboardDatabase`, so
`_accepts_context` returns `False`. The handler is called with zero positional
arguments → `TypeError`.

### Phase 4: Compare Against the Established Pattern

Check other system tools to confirm the expected convention:

```
grep: ^def \w+\(   in   deverino/harness_poc/system_tools/*.py
```

All other tools that need database access follow the `ctx: ToolContext` pattern:

| Tool | First Parameter |
|------|----------------|
| `acdl_inspect` | `ctx: ToolContext` |
| `container_destroy` | `ctx: ToolContext` |
| `container_spawn` | `ctx: ToolContext` |
| `execute_python` | `ctx: ToolContext` |
| **`_list_corpora`** | **`database: BlackboardDatabase`** ← outlier |

**Finding:** `_list_corpora` is the sole outlier that takes a raw database
parameter instead of a `ToolContext`.

### Phase 5: Verify Downstream Dependencies

Even if the signature is fixed, `_list_corpora` calls methods on `database`
that must exist on whatever object `ToolContext.database` provides at runtime.
At runtime, `ToolContext.database` is a `BlackboardAccessProxy` (injected by
`ToolRunner`). Check whether the proxy exposes all needed methods:

```
read_file: deverino/harness_poc/core/storage/blackboard_proxy.py
```

Methods `_list_corpora` calls:

| Method | On `BlackboardAccessProxy`? |
|--------|---------------------------|
| `get_all_corpus_keys()` | **MISSING** |
| `get_pending_corpus_keys()` | Yes |
| `get_context_maps(keys)` | Yes |
| `get_cycle(key)` | Yes |

**Finding:** `get_all_corpus_keys()` is the one method missing from the proxy.

### Phase 6: Confirm Why Tests Don't Catch This

Read the test file:

```
read_file: deverino/tests/system_tools/test_list_corpora.py
```

Every test calls `_list_corpora(database=db)` directly with a raw
`BlackboardDatabase` instance. They bypass `ToolRunner.execute_tool()`
entirely, so the `_accepts_context` gate and proxy layer are never exercised.

**Finding:** Tests cover the handler's internal logic but not the execution
path that matters — the `ToolRunner` invocation used in production.

### Phase 7: Check for Secondary Issues (N+1)

While reading the handler, note that `get_cycle(ck)` is called inside a loop
over all corpora — an N+1 query pattern already flagged in the project's own
refactor notes:

```
docs/refactors/2026-05-24-multi-corpus-deferred-refactors.md:150-162
```

> For each corpus in `db.get_context_maps(related)`, the rendering loop calls
> `db.get_cycle(corpus_key)` individually. With N related corpora this is N
> queries — same shape as the `_list_corpora` N+1 that *was* fixed.

**Finding:** The N+1 is a performance concern, not a correctness bug. Fixing
it in the same change would be efficient.

## Root Cause Summary

Two gaps combine to break the tool:

1. **Design gap — wrong parameter pattern.** `_list_corpora` takes
   `database: BlackboardDatabase` directly instead of `ctx: ToolContext`,
   so `ToolRunner._accepts_context()` returns `False` and no database is
   injected. The handler is called with zero positional arguments and the
   required `database` parameter is never satisfied → `TypeError`.

2. **Proxy gap — missing method.** `BlackboardAccessProxy` does not expose
   `get_all_corpus_keys()`, so even after fixing the signature, the tool
   would fail at runtime when accessing `ctx.database.get_all_corpus_keys()`.

## Implementation Spec — Handoff-Ready

Four changes across three files, plus a test rewrite. Every change includes
the exact code to write. An agent receiving this spec should not need to guess
at constructors, imports, or placement.

### Change 1: `harness_poc/system_tools/corpus_tools.py` — Accept `ToolContext` + batch cycle lookup

Replace the entire file. The key differences from the current version:

- First parameter changes from `database: BlackboardDatabase` to `ctx: ToolContext`.
  This causes `ToolRunner._accepts_context()` to return `True`, so the runner
  injects a `ToolContext` with `database` set to the session's `BlackboardAccessProxy`.
- Access all database methods through `ctx.database` with a `None` guard.
- Replace the per-corpus `database.get_cycle(ck)` loop with a single batch
  `database.get_cycles(all_keys)` call (requires Change 3 below).
- Remove the `TYPE_CHECKING` block — `BlackboardDatabase` is no longer referenced.
- Import `ToolContext` from `harness_poc.core.tools` (same import used by
  `container_spawn.py`, `execute_python.py`, etc.).

```python
"""LLM-callable tool: inventory of context-map corpora."""

from __future__ import annotations

from typing import Any

from harness_poc.core.tools import ToolContext
from harness_poc.system_tools import register as _register


def _list_corpora(ctx: ToolContext, **_: Any) -> dict[str, Any]:
    database = ctx.database
    if database is None:
        return {"error": "No database available"}

    all_keys = database.get_all_corpus_keys()
    if not all_keys:
        return {"corpora": []}

    pending_keys = set(database.get_pending_corpus_keys())
    all_maps = database.get_context_maps(all_keys)
    cycles = database.get_cycles(all_keys)  # batch lookup — see Change 3

    out: list[dict[str, Any]] = []
    for ck in all_keys:
        entries = all_maps.get(ck, [])
        out.append(
            {
                "key": ck,
                "materialized": bool(entries),
                "entry_count": len(entries),
                "cycle": cycles.get(ck, 0),
                "has_pending_events": ck in pending_keys,
            }
        )
    return {"corpora": out}


_register(
    name="list_corpora",
    description=(
        "Return a structured inventory of every context-map corpus the "
        "harness knows about, including entry counts, current cycle, and "
        "whether pending events are queued. Use this to discover valid "
        "corpus_key values before observing or citing into a corpus."
    ),
    parameters={"type": "object", "properties": {}, "required": []},
    handler=_list_corpora,
)
```

### Change 2: `harness_poc/core/storage/blackboard_proxy.py` — Add `get_all_corpus_keys`

Insert this method in the **read methods** section of `BlackboardAccessProxy`,
adjacent to the existing `get_pending_corpus_keys` and `get_context_maps` methods
(currently around line 112).

```python
def get_all_corpus_keys(self) -> list[str]:
    self._require_read()
    return self._db.get_all_corpus_keys()
```

### Change 3: `harness_poc/core/storage/database.py` + `blackboard_proxy.py` — Batch `get_cycles`

**3a.** Add `get_cycles` to `BlackboardDatabase` (insert after the existing
`get_cycle` method at `database.py:632`):

```python
def get_cycles(self, corpus_keys: list[str]) -> dict[str, int]:
    """Bulk read-only cycle_n lookup. Keys not found default to 0."""
    if not corpus_keys:
        return {}
    with Session(self._engine) as session:
        rows = session.exec(
            select(DbContextMapCycle).where(
                col(DbContextMapCycle.corpus_key).in_(corpus_keys)
            )
        ).all()
    return {row.corpus_key: row.cycle_n for row in rows}
```

Imports needed at the top of `database.py` (already present — `Session`,
`DbContextMapCycle`, and `col` are all used by the existing `get_context_maps`):
- `from sqlalchemy import col`
- `from sqlmodel import Session, select`
- `from harness_poc.core.storage.models import DbContextMapCycle`

**3b.** Add `get_cycles` to `BlackboardAccessProxy` (insert adjacent to the
new `get_all_corpus_keys` from Change 2):

```python
def get_cycles(self, corpus_keys: list[str]) -> dict[str, int]:
    self._require_read()
    return self._db.get_cycles(corpus_keys)
```

### Change 4: `tests/system_tools/test_list_corpora.py` — Test through real execution path

Replace the entire test file. Every test now constructs a `ToolContext` wrapping
a `BlackboardAccessProxy` with `read` blackboard permissions — matching the exact
path `ToolRunner.execute_tool()` takes in production.

Key details:
- `BlackboardAccessProxy(db, SkillPermissions(blackboard="read"))` — read-only,
  since `list_corpora` never writes.
- `ToolContext` constructor needs `session_id`, `project_root`, `database`.
  `runtime_config`, `cancellation`, and `system_prompt` all have defaults.
- `project_root` can be `Path.cwd()` (the tool doesn't access the filesystem).
- `session_id` can be any string (the tool doesn't use session-scoped memory).
- Call `_list_corpora(ctx=ctx)` instead of `_list_corpora(database=db)`.

```python
"""Tests for list_corpora system tool — Gap 1c."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import Engine

from harness_poc.core.context_map.schema import MapEntry
from harness_poc.core.permissions import SkillPermissions
from harness_poc.core.storage import BlackboardDatabase
from harness_poc.core.storage.blackboard_proxy import BlackboardAccessProxy
from harness_poc.core.tools import ToolContext
from harness_poc.system_tools.corpus_tools import _list_corpora


def _make_context(db: BlackboardDatabase) -> ToolContext:
    """Construct a ToolContext matching what ToolRunner injects."""
    proxy = BlackboardAccessProxy(db, SkillPermissions(blackboard="read"))
    return ToolContext(
        session_id="test-session",
        project_root=Path.cwd(),
        database=proxy,
    )


def _entry(key: str, section: str) -> MapEntry:
    now = datetime.now(tz=UTC)
    return MapEntry(
        entry_id=f"{key}-id",
        key=key,
        section=section,
        observation_type="schema",
        summary="x",
        priority=0.8,
        source_event_ids=[],
        first_seen=now,
        last_updated=now,
        materialization_count=0,
        first_seen_cycle=1,
        last_seen_cycle=1,
        token_estimate=5,
    )


def test_list_corpora_returns_structured_inventory(
    db_engine: Engine,
) -> None:
    db = BlackboardDatabase(db_engine)
    db.create_tables()
    db.write_map_and_mark_processed(
        "deverino:codebase",
        map_entries=[_entry(key="x", section="entities")],
        token_count=10, event_ids=[],
    )
    ctx = _make_context(db)
    result = _list_corpora(ctx=ctx)

    assert result == {
        "corpora": [
            {
                "key": "deverino:codebase",
                "materialized": True,
                "entry_count": 1,
                "cycle": 0,
                "has_pending_events": False,
            },
        ],
    }


def test_list_corpora_empty_database(db_engine: Engine) -> None:
    db = BlackboardDatabase(db_engine)
    db.create_tables()
    ctx = _make_context(db)
    result = _list_corpora(ctx=ctx)
    assert result == {"corpora": []}


def test_list_corpora_reports_pending_events(db_engine: Engine) -> None:
    from harness_poc.core.events import MapEntryReferenced

    db = BlackboardDatabase(db_engine)
    db.create_tables()
    db.write_map_and_mark_processed(
        "deverino:codebase",
        map_entries=[_entry(key="x", section="entities")],
        token_count=10, event_ids=[],
    )
    db.append_context_map_event(
        MapEntryReferenced(
            session_id="s", corpus_key="deverino:dashboard",
            entry_id="a" * 32, entry_key="y",
            section="insights", cycle_n=0, citation_context="ctx",
        ),
    )

    ctx = _make_context(db)
    result = _list_corpora(ctx=ctx)
    corpora = {c["key"]: c for c in result["corpora"]}

    assert corpora["deverino:codebase"]["has_pending_events"] is False
    assert corpora["deverino:dashboard"]["materialized"] is False
    assert corpora["deverino:dashboard"]["entry_count"] == 0
    assert corpora["deverino:dashboard"]["has_pending_events"] is True
```

### Type-System Note

`ToolContext.database` is declared as `ToolDatabase | None` (a Protocol with
only `read_memory`, `list_memory_keys`, `write_memory`). At runtime it is
always a `BlackboardAccessProxy`. The `_list_corpora` handler accesses methods
beyond the protocol (`get_all_corpus_keys`, `get_context_maps`, etc.). This
works at runtime because the proxy has them; the type checker will flag them.

No protocol change is needed — `ToolDatabase` intentionally captures only the
common-denominator methods that most tools need. Corpus-specific tools accept
the broader proxy type at runtime. If this pattern grows, a future refactor
could introduce a `CorpusDatabase` protocol — but that is out of scope here.

---

## Verification

```bash
# Unit tests
uv run pytest tests/system_tools/test_list_corpora.py -v

# New batch method
uv run pytest tests/storage/test_corpus_inventory.py -v

# Type check (expect corpus_tools.py to pass — ToolContext is recognized)
uv run ty check harness_poc/system_tools/corpus_tools.py

# Lint
uv run ruff check harness_poc/system_tools/corpus_tools.py

# Manual smoke
uv run harness-poc
# → "what corpora are available?" — should trigger a list_corpora call
# → expect structured inventory output without TypeError
```

## Template: How to Investigate a Tool-Invocation Bug

The methodology above generalizes. When a tool reports a missing argument,
wrong type, or unexpected `None`:

1. **Locate the handler** — search for the tool name, find the function and
   its `_register(...)` call.
2. **Read the execution path** — `ToolRunner.execute_tool()` is the bridge
   between LLM arguments and handler invocation.
3. **Check the gate** — `_accepts_context()` and `_accepts_cancellation()`
   control what gets injected. If the handler expects something the gate
   doesn't recognize, it won't be injected.
4. **Compare against peers** — check how other tools in the same directory
   handle the same dependency. Outliers are bugs.
5. **Verify the proxy layer** — if the handler accesses `ctx.database`, check
   `BlackboardAccessProxy` exposes every method the handler calls.
6. **Read the tests** — confirm whether tests exercise the `ToolRunner` path
   or shortcut directly to the handler.
