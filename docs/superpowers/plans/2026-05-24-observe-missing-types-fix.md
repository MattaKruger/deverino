# Fix: Allow observe tool to accept all seven ObservationType values

**Date**: 2026-05-24
**Status**: draft

## Problem

The `observe` tool rejects `boundary`, `constant`, and `result` as unknown
observation types. Only `entity`, `schema`, `insight`, and `dispute` are
accepted.

This creates a mismatch: the codebase schema and distiller prompt both define
all seven types, but the tool gatekeeper only allows four.

## Root Cause

Two coupled places in `skills/observe/`:

| Location | Problem |
|---|---|
| `SKILL.md` L22-26 | `observation_type` enum lists only 4 values |
| `skill.py` L34-64 | `if/elif` chain only handles 4 types; else branch returns `"Unknown observation_type"` |

Additionally, `harness_poc/core/events/context_map_events.py` has no event
classes for the three missing types, so even if accepted they'd have nothing
to emit.

Meanwhile the rest of the codebase already defines all seven:

| Source | Evidence |
|---|---|
| `schema.py` `ObservationType` Literal (L10-18) | `entity, schema, insight, dispute, boundary, constant, result` |
| `distiller_v1.md` prompt (L14, L31-39) | All 7 types with semantic descriptions |
| Deterministic cartographer design spec | References all 7 in examples |

## Semantic definitions (from distiller_v1.md)

- **`boundary`** — what is NOT in the corpus (prevents hallucination):
  missing files, absent features, undocumented areas.
- **`constant`** — a stable domain constant (a configuration value,
  a magic number, a fixed name).
- **`result`** — a reusable computation or analysis result that
  need not be re-derived.

## Fix: four files

### 1. `harness_poc/core/events/context_map_events.py`

Add three new event classes and register them:

```python
class BoundaryIdentified(ContextMapEvent):
    event_type: Literal["boundary_identified"] = "boundary_identified"
    boundary_description: str
    detail: str


class ConstantDocumented(ContextMapEvent):
    event_type: Literal["constant_documented"] = "constant_documented"
    constant_summary: str
    detail: str


class ResultRecorded(ContextMapEvent):
    event_type: Literal["result_recorded"] = "result_recorded"
    result_summary: str
    detail: str
```

Add entries to `CONTEXT_MAP_EVENT_REGISTRY`:

```python
"boundary_identified": BoundaryIdentified,
"constant_documented": ConstantDocumented,
"result_recorded": ResultRecorded,
```

### 2. `harness_poc/core/events/__init__.py`

Add the three new classes to the import block and to `__all__`:

```python
from harness_poc.core.events.context_map_events import (
    ...
    BoundaryIdentified,
    ConstantDocumented,
    ResultRecorded,
    ...
)
```

Add to `__all__`:

```python
"BoundaryIdentified",
"ConstantDocumented",
"ResultRecorded",
```

### 3. `skills/observe/skill.py`

Add imports:

```python
from harness_poc.core.events import (
    BoundaryIdentified,
    ConstantDocumented,
    ContextualInsightDiscovered,
    EntityReferenced,
    FactDisputed,
    ResultRecorded,
    SchemaDiscovered,
)
```

Add three `elif` branches after the `insight` branch (L57-64):

```python
elif observation_type == "boundary":
    event = BoundaryIdentified(
        session_id=ctx.session_id,
        corpus_key=corpus_key,
        boundary_description=summary,
        detail=detail,
    )
elif observation_type == "constant":
    event = ConstantDocumented(
        session_id=ctx.session_id,
        corpus_key=corpus_key,
        constant_summary=summary,
        detail=detail,
    )
elif observation_type == "result":
    event = ResultRecorded(
        session_id=ctx.session_id,
        corpus_key=corpus_key,
        result_summary=summary,
        detail=detail,
    )
```

### 4. `skills/observe/SKILL.md`

Update the `observation_type` field in the frontmatter YAML:

```yaml
observation_type:
  type: string
  description: >-
    What kind of observation. Pick the most specific match:
    - "entity": You identified a key class, function, module, or concept
    - "schema": You discovered a data format, config shape, or API contract
    - "dispute": You found a stale or incorrect entry in the current context map
    - "insight": You noticed a non-obvious relationship between components
    - "boundary": You identified something definitively NOT in the codebase
      (missing file, absent feature, undocumented area). Prevents hallucination.
    - "constant": You documented a stable domain constant (config value,
      magic number, fixed name).
    - "result": You recorded a reusable computation or analysis result
      that need not be re-derived.
  enum:
    - entity
    - schema
    - dispute
    - insight
    - boundary
    - constant
    - result
```

Update the event mapping table at the bottom:

```markdown
| observation_type | ContextMapEvent emitted     |
|------------------|----------------------------|
| entity           | EntityReferenced            |
| schema           | SchemaDiscovered            |
| dispute          | FactDisputed                |
| insight          | ContextualInsightDiscovered |
| boundary         | BoundaryIdentified          |
| constant         | ConstantDocumented          |
| result           | ResultRecorded              |
```

## Files NOT changed

- `schema.py` — already has all seven types in `ObservationType` Literal
- `distiller_v1.md` — already documents all seven types
- `context_map/__init__.py` — exports `ObservationType`; no change needed

## Risk assessment

- **Low risk.** The event classes are additive — no existing code references
  `boundary`, `constant`, or `result` observation types, so no existing
  behavior changes.
- The deterministic cartographer's `DistilledBatch` schema already accepts
  all seven types via the `ObservationType` Literal, so the pipeline won't
  reject these events.
- New event classes follow the same pattern as the existing four. They are
  registered in the same registry and will be deserialized identically.
