---
title: "V2 EventBus Unification — Multi-Mode Runtime"
date: 2026-06-13
status: draft
kind: plan
---
# V2 EventBus Unification — Multi-Mode Runtime

## Goal

Replace the v2 stub `EventBus` adapter with a real publish/subscribe event bus backed by the
existing v1 `EventBus` infrastructure. Route all v2 event writes through the bus so that the
pipeline mode and future agentic-loop modes (ReAct, RALPH, etc.) share a single persistence +
dispatch mechanism. Extract the pipeline into a bus subscriber, then add ReAct subscribers as
a second mode — selectable at boot with zero edits to existing code.

## Current State

- The v2 `EventBus` protocol exists in `contracts/event_runtime.py` and is fully typed.
- The adapter in `wiring.py:_build_event_bus_adapter` is a no-op — all three methods (`subscribe`,
  `unsubscribe`, `publish`) are `pass`.
- v2 code writes events through two inconsistent paths:
  - `context_engine.py` and `execution_engine.py` call `db.append_context_event()` directly,
    bypassing the bus.
  - `delegate_task_handler.py` calls `event_bus.publish()` — but the bus does nothing.
- The `WorkflowOrchestrator` is a monolithic coordinator. It calls `ContextEngine` and
  `ExecutionEngine` directly in a synchronous 3-step method (`execute_workflow`), not as a
  subscriber reacting to events.
- v1 has a fully working `EventBus` in `harness_poc/core/events/event_bus.py` with async
  pub/sub, typed events, persistent storage, and session-scoped subscriptions. Three workers
  (llm, tool, circuit_breaker) already use it for the ReAct loop.
- The v2 contracts (`ContextMapMaterializer`, `SubAgentSpawner`, `GoalRunner`, `EventBus`)
  are mode-agnostic — they don't assume pipeline or agentic-loop usage.

## Proposed Changes

### Phase 2a: Real EventBus adapter

**File:** `harness_poc/v2/wiring.py`

Replace `_build_event_bus_adapter` with an adapter that wraps the v1 `EventBus`. The adapter
translates between v2's string-based contract (`publish(event_type: str, payload: dict)`) and
v1's typed event classes.

The translation layer:

- v2 `publish("GATE_PASSED", {"passed": True, ...})` → creates a lightweight v2 event wrapper
  (a dataclass/Pydantic model carrying `event_type` + `payload` as a dict), persists it via the
  v1 `EventStore`, and dispatches to registered subscribers.
- v2 `subscribe("GATE_PASSED", handler)` → registers the handler in a lookup table. When a
  matching event is published, the handler is called with `(event_type, payload)`.
- The v1 bus's session-scoped subscription (`subscribe_session(session_id)`) is exposed as an
  optional async generator for mode subscribers that need it.

The adapter does NOT require changes to the v2 contract — the protocol already defines the
right interface. The adapter is the implementation.

**Verification:** `uv run pytest harness_poc/v2/tests/ -k event_bus -v` (add test if missing).

---

### Phase 2b: Extract pipeline into a bus subscriber

**New file:** `harness_poc/v2/subscribers/pipeline_runner.py`
**Modified:** `harness_poc/v2/workflow_orchestrator.py`

The `WorkflowOrchestrator` currently owns the 3-step pipeline as a monolithic method
(`execute_workflow`). Extract it into a `PipelineStepRunner` subscriber class that:

1. Subscribes to `WORKFLOW_STARTED` events.
2. Runs the probe step, publishes `PROBE_COMPLETED`.
3. Subscribes to its own `PROBE_COMPLETED` → runs execution step, publishes `EXECUTION_COMPLETED`.
4. Subscribes to `EXECUTION_COMPLETED` → runs the gate, publishes `GATE_COMPLETED`.

The orchestrator becomes a thin factory: it constructs the `PipelineStepRunner`, registers it
on the bus, and publishes `WORKFLOW_STARTED`. The pipeline then runs itself via event callbacks.

Step boundary events (new):

| Event type | Payload | Published by |
|------------|---------|-------------|
| `WORKFLOW_STARTED` | `{workflow_id, goal, persona_id}` | Orchestrator factory |
| `PROBE_COMPLETED` | `{probe_id, success, constraints[]}` | PipelineStepRunner |
| `EXECUTION_COMPLETED` | `{execution_id, sub_agents[], all_passed}` | PipelineStepRunner |
| `GATE_COMPLETED` | `{gate_id, passed, test_count}` | PipelineStepRunner |

These replace the ad-hoc event type strings currently embedded in `context_engine.py`
(`PROBE_FAILED`, `CONTEXT_WARMED`) and `execution_engine.py` (`GATE_PASSED`, `GATE_FAILED`).

**Verification:** Existing workflow orchestrator tests still pass. New test verifies that
publishing `WORKFLOW_STARTED` triggers the full pipeline.

---

### Phase 2c: ReAct mode subscribers

**New files:** `harness_poc/v2/subscribers/llm_worker.py`, `tool_worker.py`, `circuit_breaker.py`, `goal_evaluator.py`

Port v1's four workers to v2 contracts. The port is mechanical — the core logic is already
isolated:

| v1 worker | v2 subscriber | Key change |
|-----------|--------------|------------|
| `run_llm_worker` | `LlmWorker` | Uses v2 `ContextEngine` for prompt construction instead of raw system prompt; depends on `PydanticAgentRuntime` (unchanged) |
| `run_skill_worker` | `ToolWorker` | Uses v2 `SubAgentSpawner` contract instead of v1 `SkillRunner` directly; tool execution is the same pattern |
| `run_circuit_breaker` | `CircuitBreaker` | Nearly unchanged — just wraps the v2 bus |
| (none) | `GoalEvaluator` | New: evaluates whether the goal is complete, publishes `GOAL_EVALUATED`. Extracted from v1's `goal_runner.py` evaluate step |

Event vocabulary for ReAct mode:

| Event type | Payload | Published by |
|------------|---------|-------------|
| `AGENT_INPUT` | `{content, session_id}` | User input handler |
| `TOOL_REQUESTED` | `{skill_name, arguments}` | LlmWorker |
| `TOOL_COMPLETED` | `{tool_name, status, content}` | ToolWorker |
| `LLM_TEXT_EMITTED` | `{content}` | LlmWorker |
| `LLM_ACTION_EMITTED` | `{tokens_used, model}` | LlmWorker |
| `STREAM_PAUSED` | `{reason, threshold}` | CircuitBreaker |
| `GOAL_EVALUATED` | `{is_complete, reasoning}` | GoalEvaluator |

**Verification:** Port v1's existing processor tests. Add integration test: publish `AGENT_INPUT`,
assert the full ReAct loop runs to completion.

---

### Phase 2d: Mode selection

**Modified:** `harness_poc/v2/wiring.py`, `harness_poc/app_factory.py`, `harness_poc/cli.py`

Add a `mode` parameter to the runtime bootstrap. At startup, the wiring selects which
subscribers to attach:

```python
def build_runtime(config, mode: str = "pipeline"):
    bus = build_event_bus_adapter(config)

    if mode == "pipeline":
        pipeline = PipelineStepRunner(context_engine, execution_engine)
        bus.subscribe("WORKFLOW_STARTED", pipeline.handle)
    elif mode == "react":
        bus.subscribe("AGENT_INPUT", LlmWorker(...).handle)
        bus.subscribe("TOOL_REQUESTED", ToolWorker(...).handle)
        bus.subscribe("TOOL_COMPLETED", CircuitBreaker(...).handle)
        bus.subscribe("TOOL_COMPLETED", GoalEvaluator(...).handle)
    # Future modes: elif mode == "ralph": ...

    return bus
```

CLI surface:

```text
harness-poc run --mode pipeline "implement a test for the context engine"
harness-poc run --mode react "write a function that checks file permissions"
harness-poc chat --mode react                           # conversational ReAct
```

Default mode is `"pipeline"` — backward compatible with current behavior.

**Verification:** CLI test for `--mode pipeline` (existing behavior preserved). CLI test for
`--mode react` (subscribers attached, loop runs).

## Risks

- **Event type string proliferation.** Without a registry, typos in event type strings cause
  silent failures. Mitigation: define all event type constants in a single module
  (`v2/events.py` or the contracts `__init__.py`), mirroring v1's `EVENT_REGISTRY` pattern.

- **Pipeline subscriber re-entrancy.** If `PipelineStepRunner` subscribes to its own events
  and publishes new ones from handlers, infinite recursion is possible. Mitigation: the
  subscriber explicitly unsubscribes from an event type after handling it once, or uses a
  step counter to bound recursion.

- **Adapter impedance mismatch.** v1 `EventBus` uses `BaseEvent` subclasses; v2 contract uses
  string event types. The translation layer adds indirection. Mitigation: the v2 adapter's
  internal event wrapper is a single lightweight class, not a per-type hierarchy. If the
  overhead matters later, add typed event classes behind the contract without changing callers.

- **Breaking existing pipeline behavior.** Extracting the orchestrator into a subscriber
  changes the call stack (sync → event-driven). Mitigation: the subscriber wraps the existing
  `run_probe`/`run_execution`/`run_gate` methods unchanged — only the dispatch mechanism
  changes. Existing tests catch regressions.

- **v1 workers depend on v1 `EventBus` internals.** The port to v2 subscribers must not break
  the v1 ReAct loop that the current harness uses. Mitigation: add v2 subscribers as new code,
  do not modify v1 processors. Both can coexist during the transition.

## Acceptance Criteria

- [ ] **Phase 2a:** `event_bus.publish("test", {...})` persists an event row in the database.
  `bus.subscribe("test", handler)` fires the handler when a matching event is published.

- [ ] **Phase 2a:** All v2 event writes (`context_engine.py`, `execution_engine.py`,
  `delegate_task_handler.py`) flow through `event_bus.publish()`, not `db.append_context_event()`.

- [ ] **Phase 2b:** Publishing `WORKFLOW_STARTED` triggers the full Probe → Execute → Gate
  pipeline. Existing workflow tests pass unchanged.

- [ ] **Phase 2b:** Adding a logging subscriber (subscribes to all `PROBE_*`, `EXECUTION_*`,
  `GATE_*` events) requires zero edits to `PipelineStepRunner`.

- [ ] **Phase 2c:** Publishing `AGENT_INPUT` triggers a complete ReAct loop (LLM → tool call →
  LLM → text response). A v1-comparable integration test passes.

- [ ] **Phase 2c:** A `CircuitBreaker` subscriber publishes `STREAM_PAUSED` after N consecutive
  failures or token budget exhaustion, halting the loop.

- [ ] **Phase 2d:** `harness-poc run --mode pipeline` runs the pipeline (existing behavior).
  `harness-poc run --mode react` runs the ReAct loop.

- [ ] **Phase 2d:** Adding a new mode (e.g. `--mode ralph`) requires one new subscriber file
  and one `elif` branch in `build_runtime`. Zero edits to existing subscribers, contracts, or
  engines.

- [ ] All phases: `uv run ruff check .` and `uv run ty check` pass.
