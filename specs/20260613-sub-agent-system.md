---
title: "V2 Sub-Agent System — Unified Spawning, Lifecycle Events, and Pool Management"
date: 2026-06-13
status: draft
kind: spec
reviewed: 2026-06-13 (15 issues resolved — see Review Notes)
---
# V2 Sub-Agent System — Unified Spawning, Lifecycle Events, and Pool Management

## Objective

Unify sub-agent spawning through the V2 `SubAgentSpawner` protocol and `ExecutionEngine`, add
proper event-sourced lifecycle tracking (`SubAgentDispatched` → `SubAgentCompleted`), support
optional session isolation, and provide foreground/background pool management — all with a
single entry point. Deprecate the V1 `delegate_task` skill's inline agent creation.

## Background

The codebase has two parallel sub-agent spawning paths, neither complete:

| Aspect | V1 Skill Path (`delegate_task/skill.py`) | V2 Handler Path (`_handle_delegate_task`) |
|--------|------------------------------------------|-------------------------------------------|
| Trigger | LLM emits `SkillRequested` | `WorkflowOrchestrator.run_spec_execution()` |
| Agent creation | Inline in skill body | Via `SubAgentSpawner` protocol |
| Events emitted | `SkillCompleted` with JSON payload | `DelegateTaskCompleted` |
| Session model | Reuses parent `session_id` | Reuses parent `session_id` |
| Pool management | None | Foreground/background via `ExecutionEngine` |
| Status mapping | None | Binary→ternary via `map_delegated_to_external()` |

Both paths converge on building a PydanticAI Agent with a persona template + objective, but:

- `SubAgentDispatched` and `SubAgentCompleted` events are **defined in the registry but never
  emitted** by either path. They carry `sub_session_id` — a field that nothing populates.
  Both fields are typed as required `str` (not optional), so they need a schema change to
  support `isolate_session=False`.
- The V1 skill path has **no pool management, no status mapping, and no lifecycle events**
  beyond `SkillCompleted`.
- The V2 handler path has **no sub-session support** — `DelegateTaskCompleted` carries only
  `task_id`, not `sub_session_id`.
- `DbSession` has **no `parent_session_id` field**. The `EventStore` is scoped to a single
  `session_id`.
- Session isolation does not exist: sub-agents write to the parent's `BlackboardDB` under a
  `memory_key`, interleaving their state with the parent's.
- `_HarnessSpawner` (the production `SubAgentSpawner` adapter) only implements `spawn()` — not
  `spawn_async()` or `spawn_streaming()`.
- The `on_text: Callable[[str], None] | None` parameter on `spawn_sub_agent()` is accepted
  but silently ignored (annotated `# noqa: ARG002`).

## Design Decisions

### 1. Single entry point: `ExecutionEngine.spawn_sub_agent()`

The V2 `ExecutionEngine` becomes the **only** way to spawn a sub-agent. The V1
`delegate_task/skill.py` is reduced to a thin wrapper that calls `ExecutionEngine.spawn_sub_agent()`
— it stays as a skill for backward compatibility but no longer creates agents directly.

Rationale:
- One code path for status mapping, event emission, blackboard writes, and pool management.
- The `SubAgentSpawner` protocol already abstracts agent creation — the V1 skill's inline agent
  creation is a duplicate.
- The V2 handler's 7-step pipeline (validate → build spec → spawn → map status → build output →
  write → emit event) is the correct sequence. It just needs to also emit `SubAgentDispatched` and
  `SubAgentCompleted`.

### 2. Sub-session IDs: optional, not mandatory

Sub-agents **may** receive a `sub_session_id` for isolated event streams, but it is not required
for every spawn. The default is flat (reuse parent `session_id`), matching current behavior.

When `isolate_session=True`:
- A new UUID `sub_session_id` is generated and passed to the `SubAgentSpawner` via `task_spec["session_id"]`.
- `SubAgentDispatched` and `SubAgentCompleted` carry this `sub_session_id`.
- The sub-agent's own events (AgentStarted, LLMTextEmitted, etc.) are scoped to the sub-session.
- **Blackboard write**: The result (`DelegatedTaskOutput`) is written using the **parent**
  `session_id` so the parent can read the result. The sub-agent writes its own intermediate state
  to the sub-session's blackboard scope.

When `isolate_session=False` (default):
- `sub_session_id` is `None` on both lifecycle events.
- The parent `session_id` is reused throughout.
- All events land in the parent's event stream.

Rationale:
- True session isolation is the right design for observability (you can query a sub-agent's full
  event stream independently), but it requires `DbSession.parent_session_id` and `EventStore`
  changes that are breaking.
- Making it optional lets us ship the lifecycle events and pool management first, then add
  session isolation as a follow-up without a flag day.

### 3. Lifecycle events: always emitted, even on failure

Every sub-agent spawn emits exactly two lifecycle events, in order, with no gaps:

1. `SubAgentDispatched(session_id, task_id, sub_session_id?, persona, objective)` — before execution.
2. `SubAgentCompleted(session_id, task_id, sub_session_id?, status, content)` — after execution,
   **guaranteed** via try/finally. If the spawner throws, `status="failed"` and `content` carries
   the exception message.

`DelegateTaskCompleted` is **not** emitted by the new implementation. The event exists in the
registry but is not consumed by any production code — `WorkflowOrchestrator` calls
`spawn_sub_agent()` directly and consumes the returned value, not the event. The only references
are in tests (`test_delegate_task_handler.py`, `test_v2_fusion.py`). `DelegateTaskCompleted` is
left in the registry (no breaking schema change) but the handler stops emitting it.

Rationale:
- Event sourcing means every state transition is an event. Spawning a sub-agent and receiving its
  result are two transitions — they deserve events. A crash during execution is still a
  transition — it must produce a `SubAgentCompleted(status="failed")`.
- `DelegateTaskCompleted` was never consumed by production code. Keeping it emitted would be
  dead code. Removing the emission (but keeping the event class) is the cleanest path.

### 4. Pool management: foreground + background with configurable cap

```
spawn_sub_agent(mode="foreground")  → blocks, returns DelegatedTaskOutput
spawn_sub_agent(mode="background")  → returns task_id immediately, runs in thread
status(task_id)                     → "running" | "done" | "failed" | "cancelled" | "unknown"
result(task_id)                     → DelegatedTaskOutput (raises TaskNotCompleteError if running)
cancel(task_id)                     → sends cancellation; emits SubAgentCompleted(status="cancelled")
```

Background execution uses `asyncio.to_thread()` to run the synchronous `_handle_delegate_task()`
in a thread. The pool dict maps `task_id → asyncio.Task`. On completion, the result is cached
and the task is removed from the active pool. On cancel, the thread is interrupted and the entry
removed.

Background tasks are capped at `max_background_agents` (default 8, configurable). When the pool
is full (len(active tasks) >= cap), `spawn_sub_agent(mode="background")` raises
`SubAgentPoolFullError`.

**Pool cleanup**: When `result(task_id)` is called on a completed task, the entry is removed from
the cache dict. When `cancel(task_id)` is called, the entry is removed immediately after the
cancellation event is emitted. There is no TTL-based eviction — callers are expected to either
call `result()` or `cancel()` for every background task.

Rationale:
- True async (`asyncio.Task` wrapping sync code via `asyncio.to_thread`) gives non-blocking
  background execution without converting the synchronous `SubAgentSpawner.spawn()` chain to
  async. This is the minimal change to get real background behavior.
- A pool cap prevents unbounded resource consumption when the LLM fires off many sub-agents.
- Explicit cleanup via `result()`/`cancel()` avoids the bug where the current `_bg_active` dict
  never removes entries and permanently exhausts capacity.

### 5. V1 delegate_task skill: thin wrapper, preserving memory format

The V1 `delegate_task/skill.py` becomes a thin adapter that calls
`ExecutionEngine.spawn_sub_agent(mode="foreground")`. It **preserves the existing blackboard
memory format** to avoid breaking callers that read `memory["status"]`,
`memory["artifacts"]["persona"]`, etc.:

```python
def execute(skill_context):
    engine = get_execution_engine(skill_context.app_state)
    result = engine.spawn_sub_agent(
        agent_type=skill_context.args["persona"],
        task_payload={"objective": skill_context.args["objective"]},
        mode="foreground",
    )
    # Preserve existing memory format for backward compatibility
    skill_context.write_memory(skill_context.args["memory_key"], {
        "status": result.output_label,
        "summary": result.summary,
        "artifacts": {
            "persona": skill_context.args["persona"],
            "model_output": result.raw_output,
            "objective": skill_context.args["objective"],
            "received_context": skill_context.args.get("context", ""),
        },
    })
    return SkillResult(status="completed", payload=result.model_dump())
```

The skill no longer loads personas, builds Agents, or manages streaming. Streaming is deferred
(Non-Goal) — the `on_text` parameter on `spawn_sub_agent()` is passed through to the spawner but
the `_HarnessSpawner` adapter does not yet implement `spawn_streaming()`.

### 6. Status mapping includes cancellation

The canonical status mapping table in `event_runtime.py` is extended:

| GoalRunner status | DelegatedTaskResult.status | DelegatedTaskOutput.output_label |
|-------------------|---------------------------|----------------------------------|
| `"success"` | `"success"` | `"completed"` |
| `"failed"` | `"failed"` | `"failed"` |
| `"blocked"` | `"failed"` | `"blocked"` (via `original_goal_status="blocked"`) |
| *(cancelled)* | n/a — spawner never returns | `"cancelled"` |

Cancellation bypasses the spawner entirely — the `asyncio.Task` is cancelled, the spawner never
returns a `DelegatedTaskResult`. The handler catches `asyncio.CancelledError`, sets
`output_label="cancelled"`, and emits `SubAgentCompleted(status="cancelled")`. The status mapping
function is not called for cancellation.

### 7. Return type contract

`spawn_sub_agent()` returns a **union type** depending on mode:

```python
@overload
def spawn_sub_agent(self, *, mode: Literal["foreground"], ...) -> DelegatedTaskOutput: ...
@overload
def spawn_sub_agent(self, *, mode: Literal["background"], ...) -> str: ...
```

`WorkflowOrchestrator.run_spec_execution()` is updated to handle both: for foreground, it
receives `DelegatedTaskOutput` directly. For background, it receives a `task_id` and polls.

Phase 1 keeps the return type as `dict[str, Any]` (current behavior) to avoid breaking the
orchestrator. Phase 2 introduces the typed return when background mode is added.

## Requirements

### R1: Single entry point
`ExecutionEngine.spawn_sub_agent()` is the only function that creates sub-agents. The V1 skill
and any future callers go through it.

### R2: Lifecycle events — always emitted in try/finally
Every spawn emits `SubAgentDispatched` before execution and `SubAgentCompleted` after execution.
If the spawner throws, `SubAgentCompleted` is emitted with `status="failed"` and `content` set to
the exception message. The two events are paired via a shared `task_id`.

### R3: DelegateTaskCompleted not emitted
`DelegateTaskCompleted` is kept in the event registry (no schema break) but the handler stops
emitting it. No production code consumes it.

### R4: Status mapping
The canonical three-layer status mapping applies to every spawn. Cancellation is handled
separately (bypasses the spawner, sets `output_label="cancelled"` directly).

### R5: Foreground/background dispatch
- `mode="foreground"` blocks until the sub-agent completes, returns `DelegatedTaskOutput`.
- `mode="background"` returns a `task_id` immediately. The sub-agent runs in a thread via
  `asyncio.to_thread()`. The caller polls via `status(task_id)` and retrieves results via
  `result(task_id)`.

### R6: Pool cap
Background sub-agents are capped at active tasks. Default: 8. Configurable via
`ExecutionEngine(max_background_agents=N)`. Pool-full raises `SubAgentPoolFullError`.

### R7: Cancellation and pool cleanup
- `cancel(task_id)` on a running task: cancels the `asyncio.Task`, emits
  `SubAgentCompleted(status="cancelled", content="Cancelled by caller")`, removes entry from pool.
- `cancel(task_id)` on an already-completed task: no-op, returns `False`.
- `cancel(task_id)` on an unknown task: raises `TaskNotFoundError`.
- `result(task_id)` on a running task: raises `TaskNotCompleteError`.
- `result(task_id)` on a cancelled task: raises `TaskCancelledError` (caller should have checked
  status first).
- `result(task_id)` on a completed task: returns `DelegatedTaskOutput`, removes entry from cache.
- `status(task_id)` on unknown task: returns `"unknown"`.

### R8: Optional session isolation
When `isolate_session=True`, the sub-agent receives a distinct `sub_session_id` via
`task_spec["sub_session_id"]`. Lifecycle events carry this value. The sub-agent's own events are
scoped to the sub-session. Blackboard writes for the sub-agent's result use the **parent**
`session_id`; the sub-agent writes its own intermediate state to the sub-session scope.

When `isolate_session=False` (default), `sub_session_id=None` on lifecycle events. The parent
`session_id` is reused throughout.

### R9: V1 skill backward compatibility
`delegate_task/skill.py` still works via `SkillRequested`. It delegates to
`ExecutionEngine.spawn_sub_agent(mode="foreground")` internally. The blackboard memory format
is preserved (`status`, `artifacts.persona`, `artifacts.model_output`, etc.). Existing tests pass
with minimal mock updates.

### R10: Testability
`SubAgentSpawner` is a protocol — tests inject a `SpawnerSpy`. `EventBus` is a protocol — tests
inject an `EventBusSpy`. No real LLM calls in unit tests. This is already the case; extend the
pattern.

### R11: Event schema changes
Both `SubAgentDispatched` and `SubAgentCompleted` gain a `task_id: str` field. Their
`sub_session_id` field changes from `str` (required) to `str | None = None`. This is a schema
migration — existing serialized events do not have these events, so no data migration is needed.

## Non-Goals

- **Full session hierarchy (`DbSession.parent_session_id`).** Session isolation in this spec
  means generating a distinct `session_id` and scoping events to it. True parent/child
  relationships in the database schema are deferred.
- **Sub-agent-to-sub-agent communication.** Sub-agents run independently. They do not message
  each other or share a blackboard.
- **Streaming sub-agent output in real time.** The `spawn_streaming()` protocol method and
  `on_text` parameter exist but are not wired end-to-end. `_HarnessSpawner` does not yet
  implement `spawn_streaming()`. Phase 4 passes `on_text` through but the adapter ignores it.
- **Persistence of background task queue across restarts.** Background tasks are in-memory. If
  the harness restarts, queued/running sub-agents are lost.
- **`spawn_async()` protocol method.** The protocol defines it, but it is not implemented by
  `_HarnessSpawner` and is not required by any caller.

## Implementation Phases

### Phase 1: Event schema + lifecycle events + try/finally

**Files to modify:**
- `harness_poc/core/events/events.py` — `SubAgentDispatched`: add `task_id: str`, change
  `sub_session_id: str` → `str | None = None`. `SubAgentCompleted`: add `task_id: str`, change
  `sub_session_id: str` → `str | None = None`.
- `harness_poc/v2/handlers/delegate_task_handler.py` — emit `SubAgentDispatched` before
  `spawner.spawn()` and `SubAgentCompleted` in try/finally after. Stop emitting
  `DelegateTaskCompleted`.
- `harness_poc/system_skills/delegate_task/skill.py` — thin wrapper (preserving memory format).
- `harness_poc/v2/contracts/event_runtime.py` — add `"cancelled"` handling (no-op entry in
  mapping table; cancellation bypasses the mapping function).

**Changes:**
1. Event classes updated with `task_id` and optional `sub_session_id`.
2. `_handle_delegate_task()`: generate `task_id` at start. Emit `SubAgentDispatched`. Wrap
   `spawner.spawn()` in try/finally — on success emit `SubAgentCompleted(status="success")`, on
   exception emit `SubAgentCompleted(status="failed", content=str(exc))`.
3. `_handle_delegate_task()` removes the `event_bus.publish(DelegateTaskCompleted(...))` call.
4. V1 skill collapsed to thin wrapper (see Design Decision 5).
5. `EVENT_REGISTRY` updated if needed (existing entries remain; new fields don't change the
   class name keys).

**Verification:**
- `test_delegate_task_handler.py`: extend SpawnerSpy tests to assert `SubAgentDispatched` and
  `SubAgentCompleted` events emitted with correct `task_id` and field values.
- `test_delegate_task_handler.py`: `TestSpawnerExplodes` updated — now asserts
  `SubAgentDispatched` + `SubAgentCompleted(status="failed")` instead of zero events.
- `test_delegate_task.py`: update mock assertions to match thin wrapper; memory format assertions
  preserved.
- `test_v2_fusion.py`: update `DelegateTaskCompleted` round-trip test — either remove or mark as
  legacy (event class still exists, just not emitted by handler).
- `test_events.py`: update `SubAgentDispatched`/`SubAgentCompleted` construction tests for new
  fields.

### Phase 2: Background pool with asyncio.to_thread, cap, cancellation, cleanup

**Files to modify:**
- `harness_poc/v2/execution_engine.py` — background mode via `asyncio.to_thread`, pool dict,
  cap enforcement, `status()`, `result()`, `cancel()`.
- `harness_poc/v2/contracts/sub_agent_spawner.py` — add `SubAgentPoolFullError`,
  `TaskNotCompleteError`, `TaskCancelledError`, `TaskNotFoundError`.
- `harness_poc/v2/workflow_orchestrator.py` — update `run_spec_execution()` to handle returned
  `DelegatedTaskOutput` (foreground) and `task_id` (background).
- `tests/v2/test_execution_engine.py` — extend.

**Changes:**
1. `ExecutionEngine` holds `_active_tasks: dict[str, asyncio.Task]` and `_results_cache: dict[str, DelegatedTaskOutput]`.
2. `spawn_sub_agent(mode="foreground")` returns `DelegatedTaskOutput` (changed from `dict`).
3. `spawn_sub_agent(mode="background")`: check capacity, create `asyncio.Task` via
   `asyncio.to_thread(_handle_delegate_task, ...)`, store in `_active_tasks`, return `task_id`.
4. On task completion (callback): move result to `_results_cache`, remove from `_active_tasks`.
5. `status(task_id)`: check `_active_tasks` → `"running"`, check `_results_cache` → `"done"`,
   check cancelled set → `"cancelled"`, else `"unknown"`.
6. `result(task_id)`: raises `TaskNotCompleteError` if running, `TaskCancelledError` if
   cancelled, returns `DelegatedTaskOutput` and removes from cache if done.
7. `cancel(task_id)`: calls `task.cancel()`, catches `CancelledError` in the task's done
   callback to emit `SubAgentCompleted(status="cancelled")`, removes from `_active_tasks`.
   No-ops if already completed, raises `TaskNotFoundError` if unknown.
8. Return type overloads added to `spawn_sub_agent()`.

**Verification:**
- New tests: pool-full raises `SubAgentPoolFullError`.
- New tests: `cancel()` on running task → `SubAgentCompleted(status="cancelled")` emitted.
- New tests: `cancel()` on completed task → no-op, returns `False`.
- New tests: `cancel()` on unknown task → raises `TaskNotFoundError`.
- New tests: `result()` on running task → raises `TaskNotCompleteError`.
- New tests: `result()` on cancelled task → raises `TaskCancelledError`.
- New tests: `result()` on completed task → returns `DelegatedTaskOutput`, removes from cache.
- New tests: `status()` transitions: `"running"` → `"done"` → (after result) `"unknown"`.
- New tests: pool capacity recovers after `result()` or `cancel()` frees a slot.
- Existing `test_execution_engine.py` tests updated for new return type.

### Phase 3: Optional session isolation

**Files to modify:**
- `harness_poc/v2/execution_engine.py` — add `isolate_session` parameter, generate sub-session ID.
- `harness_poc/v2/handlers/delegate_task_handler.py` — accept and forward `sub_session_id` in
  task_spec and events.
- `harness_poc/v2/contracts/sub_agent_spawner.py` — document that `task_spec["sub_session_id"]`
  is the mechanism for passing session isolation to the spawner.
- `tests/v2/test_execution_engine.py` — extend.

**Changes:**
1. `spawn_sub_agent(isolate_session=True)` generates `sub_session_id = uuid4()`.
2. `sub_session_id` added to `task_spec` dict before calling spawner.
3. `SubAgentDispatched` and `SubAgentCompleted` carry the `sub_session_id` value.
4. Default `isolate_session=False` → `sub_session_id=None` on events.
5. Blackboard write in handler uses **parent** `session_id` for the result (parent can always
   read its own sub-agent results). The sub-agent's internal writes use the sub-session scope if
   the spawner uses the `sub_session_id` from `task_spec`.

**Verification:**
- New test: `isolate_session=True` → `sub_session_id` is non-null UUID on both events.
- New test: `isolate_session=False` → `sub_session_id` is `None`, `session_id` matches parent.
- New test: `task_spec` passed to `SpawnerSpy` contains `sub_session_id` when isolated.
- Existing tests pass with default `isolate_session=False`.

### Phase 4: V1 skill wrapper and cleanup

**Files to modify:**
- `harness_poc/system_skills/delegate_task/skill.py` — rewrite as thin wrapper.
- `harness_poc/system_skills/delegate_task/SKILL.md` — update docs.
- `tests/skills/test_delegate_task.py` — update tests.

**Changes:**
1. Remove inline agent creation, persona loading, and streaming logic from the skill.
2. Skill calls `ExecutionEngine.spawn_sub_agent(mode="foreground")` via app state.
3. Memory format preserved (see Design Decision 5).
4. `_stream_subagent_output` removed (streaming is a Non-Goal).
5. Update `SKILL.md`: note that the skill delegates to the V2 ExecutionEngine.

**Verification:**
- `test_delegate_task.py` tests pass with updated mocks; memory format assertions unchanged.
- New test: skill execution triggers `SubAgentDispatched` and `SubAgentCompleted` on the bus
  (verify via EventBusSpy).
- Ruff and ty checks pass.

## Event Contract

| Event | When | Fields | Consumer |
|-------|------|--------|----------|
| `SubAgentDispatched` | Before execution, always | `session_id`, `task_id`, `sub_session_id?`, `persona`, `objective` | Logging, observability, TUI |
| `SubAgentCompleted` | After execution, always (try/finally) | `session_id`, `task_id`, `sub_session_id?`, `status`, `content` | Logging, observability, TUI, pool management |

`status` values: `"success"`, `"failed"`, `"cancelled"`.
`content`: on success, the `DelegatedTaskOutput.summary`; on failure, the exception message; on
cancellation, `"Cancelled by caller"`.

`DelegateTaskCompleted` remains in `EVENT_REGISTRY` but is no longer emitted by the handler.
Existing tests that verify its round-trip through the EventStore are preserved but marked as
legacy (the event class exists for schema compatibility).

## Error Paths

| Scenario | SubAgentDispatched | SubAgentCompleted | Exception |
|----------|-------------------|-------------------|-----------|
| Spawner succeeds | ✅ emitted | ✅ `status="success"` | None |
| Spawner raises | ✅ emitted | ✅ `status="failed"`, `content=str(exc)` | `SpawnerFailureError` (wrapped) |
| Task cancelled mid-run | ✅ emitted | ✅ `status="cancelled"` | `asyncio.CancelledError` (caught) |
| Pool full (background) | ❌ not emitted | ❌ not emitted | `SubAgentPoolFullError` |
| Invalid args | ❌ not emitted | ❌ not emitted | `ValueError` (before dispatch) |

**Critical invariant**: If `SubAgentDispatched` is emitted, `SubAgentCompleted` is **always**
emitted afterward — even if the spawner crashes, even if the task is cancelled. The only case
where neither event fires is a validation error before dispatch (invalid args, pool full).

## Acceptance Criteria

- [ ] **Phase 1:** `SubAgentDispatched` and `SubAgentCompleted` events have `task_id: str` and
  `sub_session_id: str | None = None`.
- [ ] **Phase 1:** Every spawn emits both lifecycle events. Spawner exceptions produce
  `SubAgentCompleted(status="failed")`. Tests cover the try/finally guarantee.
- [ ] **Phase 1:** `DelegateTaskCompleted` is no longer emitted by `_handle_delegate_task()`.
- [ ] **Phase 1:** V1 `delegate_task` skill delegates to `ExecutionEngine` and preserves
  existing memory format.
- [ ] **Phase 1:** All existing tests pass with minimal updates (event field changes, mock
  updates for thin wrapper).
- [ ] **Phase 2:** `spawn_sub_agent(mode="background")` returns `task_id` immediately. The
  sub-agent runs in a thread via `asyncio.to_thread()`.
- [ ] **Phase 2:** `status(task_id)`, `result(task_id)`, `cancel(task_id)` behave as specified
  in R7 for all states (running, done, cancelled, unknown).
- [ ] **Phase 2:** Pool cap enforced. Capacity recovers after `result()` or `cancel()`.
- [ ] **Phase 2:** `WorkflowOrchestrator.run_spec_execution()` works with the new return types.
- [ ] **Phase 3:** `isolate_session=True` → non-null `sub_session_id` on events.
  `isolate_session=False` → `None`.
- [ ] **Phase 4:** V1 `delegate_task` skill tests pass; new tests verify lifecycle event
  emission through the skill path.
- [ ] **All phases:** `uv run ruff check .` and `uv run ty check` pass.
- [ ] **All phases:** No real LLM calls in unit tests. Spies used for Spawner, EventBus,
  Blackboard.

## Review Notes (2026-06-13)

15 issues found in initial spec review. Resolved as follows:

| # | Issue | Resolution |
|---|-------|------------|
| P0 | `sub_session_id` type mismatch (`str` vs `str\|None`) | Phase 1 now explicitly changes both event classes to `str \| None = None` |
| P0 | Background pool requires async conversion | Use `asyncio.to_thread()` to wrap sync spawner — no full async conversion needed |
| P0 | Pool dict never cleaned up | Explicit cleanup on `result()` and `cancel()`; removed from R7 edge cases |
| P1 | `task_id` missing on lifecycle events | Added to both event classes in Phase 1 |
| P1 | `DelegateTaskCompleted` claimed consumers don't exist | Verified; event kept in registry but handler stops emitting it |
| P1 | Spawner exceptions break lifecycle contract | try/finally guarantee added; R2 and Error Paths table specify behavior |
| P1 | V1 memory format incompatible | Design Decision 5 preserves existing format explicitly |
| P1 | Cancellation not in status mapping | Handled separately (bypasses mapping function); documented in Design Decision 6 |
| P1 | `SubAgentSpawner` has no session_id parameter | Uses `task_spec["sub_session_id"]` convention instead of protocol change |
| P1 | `spawn_sub_agent` return type undefined | `@overload` signatures defined; Phase 2 introduces typed return |
| P1 | Missing error-path acceptance criteria | Error Paths table added; acceptance criteria cover failure/cancel/unknown cases |
| P2 | Blackboard write behavior with isolation | Specified: parent session_id for result, sub-session for internal writes |
| P2 | `_HarnessSpawner` missing `spawn_streaming` | Acknowledged as Non-Goal; Phase 4 passes `on_text` through but adapter ignores it |
| P2 | `cancel()` edge cases undefined | R7 now specifies all four states (running, completed, cancelled, unknown) |
| P2 | `SubAgentCompleted.content` semantics undefined | Event Contract table defines content per status value |
