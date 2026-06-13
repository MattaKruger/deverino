# Plan 2 — V2 Bridge Execution

> **Prerequisite:** Plan 1 contracts written to `harness_poc/v2/contracts/` (✅ done)
>
> **Goal:** Complete the 5 partial implementations that block the V2 scaffold,
> then build the thin-wrapper engines. Net-new features come last.
>
> **TDD rule:** Every partial gets 2+ tests (failure-mode + edge-case) before
> it's marked complete. No test, no merge.

---

## Phase A: Unblock the Partials (this plan)

These 5 gaps have stub/partial implementations. They block everything else.

| Step | Gap | What | Contract Depends On | Est. |
|------|-----|------|---------------------|------|
| A1 | 2 | `_handle_delegate_task` — complete handler, write to BlackboardDB, emit event | `SubAgentSpawner`, `EventBus` | 1 session |
| A2 | 3 | `_process_tool_result` — add error branches (malformed, timeout, retry) | `EventRuntime` | 1 session |
| A3 | 10a | `delegate_task_streaming` — implement async path with `on_text` callback | `SubAgentSpawner` (async) | 1 session |
| A4 | 14 | `MetadataLogger` — wire into EventBus as subscriber | `EventBus` | 1 session |
| A5 | 17 | `TaskRouter` — integrate route table into agent loop | `EventRuntime` | 1 session |

### TDD micro-cycle (mandatory per step)

```
For each partial (A1–A5):
  1. Write a test that asserts the current stub's failure mode → watch it FAIL
  2. Complete the implementation → watch it PASS
  3. Add an edge-case test (malformed input, timeout, null result) → watch it PASS
  4. Commit: test + implementation together
```

### Dependency chain within Phase A

```
A1 (_handle_delegate_task) ──┐
                              ├──► A4 (MetadataLogger) ──┐
A2 (_process_tool_result) ───┘                          ├──► Phase B
                              ┌──────────────────────────┘
A3 (delegate_task_streaming) ─┤
                              └──► A5 (TaskRouter) ──────┘
```

A1+A2 can be done in parallel (both touch the agent loop but different handlers).
A3 is independent (async path). A4 and A5 are wiring tasks that can run after
A1+A2 are done.

### Contracts reference

Each step's code can import from:

```python
from harness_poc.v2.contracts import (
    # Protocols
    SoulConstitution, ContextMapMaterializer,
    EventStore, EventBus, GoalRunner, SubAgentSpawner,
    # Data classes
    Goal, GoalResult, DbContextMap,
    DelegatedTaskResult, DelegatedTaskOutput,
    # Errors
    SoulIntegrityError, CorpusNotFoundError, MaterializationError,
    GoalExecutionError,
    # Status mapping (canonical single source of truth)
    map_goal_status_to_delegated,
    map_delegated_to_external,
)
```

---

## Phase B: Thin-Wrapper V2 Scaffold (Plan 3, first half)

Only starts after ALL Phase A steps pass their TDD gates.

| Step | Gap | What | Composes | Est. |
|------|-----|------|----------|------|
| B1 | 5 | `ContextEngine` | `SoulConstitution` + `ContextMapMaterializer` + `EventStore` | 1 session |
| B2 | 12 | `ExecutionEngine` (core) | `GoalRunner` + `SubAgentSpawner` + `EventBus` | 1 session |
| B3 | 8 | `SessionOrchestrator` | `ContextEngine` + `ExecutionEngine` | 1 session |
| B4 | 16 | `AuditTrail` | `EventStore.replay()` | 1 session |
| B5 | 11 | `delegate_task` v2 API | `SubAgentSpawner.delegate_task_streaming` | 1 session |

**Startup order** (enforced by `SessionOrchestrator`):

```
1. SoulConstitution loaded from soul.md
2. EventStore initialized (SQLite)
3. EventBus wired to EventStore
4. GoalRunner wired to EventStore + EventBus
5. ContextMapMaterializer wired to EventStore
6. SubAgentSpawner wired to GoalRunner
7. ContextEngine composed from 1+5
8. ExecutionEngine composed from 4+6+3
```

---

## Phase C: Net-New Features (Plan 3, second half)

No existing implementation. These come last.

| Step | Gap | What | Depends On | Est. |
|------|-----|------|------------|------|
| C1 | 9 | V2 Goal format (structured spec dataclass + parser) | Nothing | 1 session |
| C2 | 6 | `ContextManager` (window budgeting, eviction, prioritization) | `ContextEngine` (B1) | 2 sessions |
| C3 | 13 | `StreamingManager` (unified streaming across LLM calls) | `delegate_task_streaming` (A3) | 2 sessions |
| C4 | 15 | `MetricsCollector` (latency, token count, success rate) | `MetadataLogger` (A4) | 1 session |

---

## Full Dependency Graph

```
Phase A (partials)           Phase B (thin-wrappers)      Phase C (net-new)
══════════════════           ═══════════════════════      ════════════════

_handle_delegate_task ──┐    ContextEngine ──┐            V2 Goal format
                         ├──►                 ├──►
_process_tool_result ───┘    ExecutionEngine ─┤            ContextManager
                                │               │
delegate_task_streaming         │               ├──►
  │                             ├── SessionOrch │
  │                             │               ├──► StreamingManager
  └─────────────────────────────┤               │
                                │               ├──► MetricsCollector
MetadataLogger ─────────────────┤               │
                                │               │
TaskRouter ─────────────────────┘               └──► AuditTrail
```

---

## Risk Register

| Risk | Mitigation |
|------|------------|
| No tests exist for 5 partials | TDD micro-cycle baked into each step (2 tests min) |
| Status enum drift between 3 layers | Single source of truth in `contracts/event_runtime.py` — `map_goal_status_to_delegated()` and `map_delegated_to_external()` |
| EventStore connection lifecycle undefined | `EventStore` protocol now has `.initialize(db_path)` + `.close()`; context-manager pattern |
| Renderer ownership ambiguous | `Materializer.materialize()` calls `Renderer.render()` internally — `.rendered` always populated |

---

## Status

| Phase | Steps | Status |
|-------|-------|--------|
| Contracts (Plan 1a) | 5 `.py` files written | ✅ Done |
| Phase A | 5 partials | 🔄 A1 done (12/12 tests), A2–A5 pending |
| Phase B | 5 thin-wrappers | 🔒 Blocked on Phase A |
| Phase C | 4 net-new | 🔒 Blocked on Phase B |
