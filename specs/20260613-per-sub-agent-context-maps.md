# Per-Sub-Agent Context Maps

**Status:** spec
**Date:** 2026-06-13
**Depends on:**
- Approach A (context map injection into sub-agent prompts — `d1cf667`)
- `specs/20260613-sub-agent-system.md` (SubAgentDispatched/SubAgentCompleted event schema — adds `task_id`, optional `sub_session_id`)

## Problem

Sub-agents currently share the project's context map (`deverino:codebase`). They have no persistent context of their own — no memory of prior invocations, no task-specific orientation, no accumulated learnings. Each spawn is a blank slate beyond the persona template and injected project map.

## Design

### Corpus Key Convention

| Pattern | Example | Isolation | Use case |
|---------|---------|-----------|----------|
| `{project}:subagent:{persona}` | `deverino:subagent:architect` | Per-persona | Long-lived personas that accumulate context across invocations |
| `{project}:subagent:{persona}:{task_id}` | `deverino:subagent:coder:abc123` | Per-invocation | One-shot agents, audit trails |

**Recommendation:** `{project}:subagent:{persona}` as default. Generated automatically by `spawn_sub_agent()` — the caller does NOT need to pass `corpus_key` explicitly. The `corpus_key` field in `context_map` and `context_map_events` already accepts any string — no migration.

### Session Identity

Sub-agents get a real `DbSession` row when `isolate_session=True`:

```python
# In ExecutionEngine.spawn_sub_agent()
corpus_key = arguments.get("corpus_key") or f"{project_id}:subagent:{agent_type}"
arguments["corpus_key"] = corpus_key

if isolate_session:
    sub_session_id = str(uuid.uuid4())
    db.start_session(sub_session_id, ..., active_corpus_key=corpus_key)  # uses existing start_session()
    arguments["sub_session_id"] = sub_session_id
```

The session's `active_corpus_key` is set to the sub-agent's corpus key. This allows:
- `append_context_map_event()` to automatically scope events to the sub-agent's corpus
- Citation extraction to attribute `[entry:…]` references correctly
- Session-scoped tools (semble_search, observe) to operate in the sub-agent's context

**Note:** `DbSession.start_session()` currently auto-generates a UUID session_id and creates a `DbSession` row. It accepts an `active_corpus_key` parameter if enhanced. For Phase 1, we can pass `corpus_key` directly through `arguments` without creating a sub-session — the event scoping works via explicit `corpus_key` passthrough.

### Event Routing

Sub-agents emit context map events through two paths:

1. **Skill path**: The `append_event` skill already accepts an explicit `corpus_key` argument. The LLM (or calling code) passes the sub-agent's `corpus_key` from the task's environment.
2. **Lifecycle path**: New `ContextMapEvent` subclasses (not `BaseEvent` subtypes) carry sub-agent `corpus_key` — see Lifecycle Events below.

Events accumulate in `context_map_events` scoped to the sub-agent's corpus key. The existing `MaterializerRunner._poll_once()` automatically picks up any corpus key with unprocessed events — no pipeline changes needed.

### Materialization

The `MaterializerRunner` already polls `get_pending_corpus_keys()` which returns every distinct `corpus_key` with unprocessed events. Sub-agent corpus keys are just more keys in the pool. The Distiller → Cartographer → `write_map_and_mark_processed()` pipeline works identically.

**Deferred materialization (accepted):** Materialization happens on the MaterializerRunner's poll cycle, not on-demand. This means a sub-agent spawned for the first time gets an empty context map (the fallback path in `_HarnessSpawner.spawn()` handles this gracefully by returning an empty `DbContextMap`). The second invocation sees the first invocation's accumulated events after they've been materialized.

### Lifecycle Events

**Correction from review:** `SubAgentDispatched`/`SubAgentCompleted` in `core/events/events.py` are `BaseEvent` subtypes — they carry session lifecycle data but NOT `corpus_key` and are NOT stored in `context_map_events`. To feed sub-agent lifecycle data into the context map pipeline, we need either:

**Option A (recommended): New ContextMapEvent subtypes**
```python
# In core/events/context_map_events.py
class SubAgentTaskStarted(ContextMapEvent):
    event_type: Literal["sub_agent_task_started"] = "sub_agent_task_started"
    sub_session_id: str
    persona: str
    objective: str

class SubAgentTaskCompleted(ContextMapEvent):
    event_type: Literal["sub_agent_task_completed"] = "sub_agent_task_completed"
    task_id: str
    status: str  # success | failed
    summary: str
```
These carry `corpus_key` (inherited from `ContextMapEvent`) and are stored directly in `context_map_events` via `append_context_map_event()`. Emission happens in `delegate_task_handler.py`.

**Option B: Adapter bridge** — convert `BaseEvent` (SubAgentDispatched/Completed) to `ContextMapEvent` in `delegate_task_handler.py`. Less clean: duplicates event emission for the same logical event.

**Recommendation:** Option A. Two new event types scoped under the sub-agent's `corpus_key`, emitted at dispatch and completion.

### Prompt Assembly

The sub-agent's system prompt includes:
1. Persona template (existing)
2. Sub-agent's own context map — `{project}:subagent:{persona}`
3. Project-level context map — `{project}:codebase` (Approach A)
4. Cross-corpus enrichment (future — related sub-agent maps)

## Implementation Plan

### Phase 1: Corpus key auto-generation

| Step | File | Change |
|------|------|--------|
| 1a | `execution_engine.py` | `spawn_sub_agent()` auto-generates `corpus_key` from persona: `f"{project_id}:subagent:{agent_type}"`. Forwards through `arguments`. Callers may override. |
| 1b | `wiring.py` | `_HarnessSpawner.spawn()` uses `corpus_key` from task_spec, falls back to `f"{config.project_id}:subagent:{persona}"`. No change needed if 1a is done, but belt-and-suspenders. |

### Phase 2: Lifecycle context map events

| Step | File | Change |
|------|------|--------|
| 2a | `core/events/context_map_events.py` | Add `SubAgentTaskStarted` and `SubAgentTaskCompleted` ContextMapEvent subclasses with `corpus_key` field (inherited). |
| 2b | `handlers/delegate_task_handler.py` | Emit `SubAgentTaskStarted` before spawn, `SubAgentTaskCompleted` after result, both via `db.append_context_map_event()` with the sub-agent's `corpus_key`. |
| 2c | `skills/append_event/skill.py` | Accept `corpus_key` from session context when not explicitly provided (defensive — already accepts explicit `corpus_key`). |

### Phase 3: Session isolation (optional, deferred)

| Step | File | Change |
|------|------|--------|
| 3a | `core/storage/database.py` | Accept `active_corpus_key` parameter in `start_session()` or add `ensure_session_corpus_key()`. |
| 3b | `execution_engine.py` | When `isolate_session=True`: create sub-session with `active_corpus_key`, pass `sub_session_id` to delegate handler. |

Session isolation is deferred because even without it, event scoping works via explicit `corpus_key` passthrough to `append_context_map_event()`.

## Non-Goals

- Per-invocation event isolation (sub-agents of same persona share event stream by default)
- Real-time materialization (deferred materialization via poll cycle is sufficient)
- Sub-agent-to-sub-agent context sharing (cross-corpus comes later)
- Full session isolation for sub-agents (Phase 3 optional, not required for basic context accumulation)

## Verification

1. Spawn a "reviewer" sub-agent twice — second invocation sees first invocation's context map entries (after MaterializerRunner poll cycle)
2. Sub-agent emits `append_event` with `corpus_key="deverino:subagent:reviewer"` — event appears in `context_map_events` with correct key
3. `SubAgentTaskStarted`/`SubAgentTaskCompleted` events appear in `context_map_events` with correct `corpus_key`
4. `MaterializerRunner._poll_once()` picks up sub-agent corpus keys via `get_pending_corpus_keys()`
5. Existing tests still pass (no regression)
