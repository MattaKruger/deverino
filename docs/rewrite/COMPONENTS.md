# Deverino Rewrite — Component Extraction

A working inventory of what's in the current POC, what to carry over to the rewrite, and why.

## Conventions

### Layers

- `concept` — an architectural idea (e.g., "event-sourced runtime")
- `code` — a concrete module, class, or contract (e.g., `core/events/event_bus.py`)

A `concept` row in the inventory is followed by the `code` rows that realize it.

### Disposition

- `keep` — extract concept and code roughly as-is
- `redesign` — concept stays, implementation needs rework
- `defer` — out of scope for v1 of the rewrite, revisit later
- `drop` — not coming over
- `experiment` — still figuring out if it belongs

### Keeper template

Copy this stub for every `keep` and `redesign` entry. Promote to `docs/rewrite/components/<name>.md` with a back-link if it grows past ~200 lines.

```markdown
## <Component Name>

**Disposition:** keep | redesign
**Layer:** concept | code

**Concept:** One sentence at the architectural level.

**Current realization:**

- `path/to/code` — what's there

**Why keep:** What worked, what insight this captures. Be specific —
"events are typed and durable so we can rebuild state" beats
"good architecture."

**What to change:** Known warts, lessons learned, things to do
differently in the rewrite.

**Depends on:** Other entries in this doc this one needs.

**ACDL status:** spec'd | needs spec | N/A

**Tested via:** Pointer to one or two test files
(e.g., `tests/agent/test_goal_runner.py`). Keep it lightweight — a
path, not a chunk list.

**Notes:** Free-form.
```

## Inventory

| Component | Layer | Disposition | One-liner |
| --------- | ----- | ----------- | --------- |
|           |       |             |           |

## Keepers

<!-- Use the keeper template above for each entry. Pre-seeded slots below. -->

### Event-sourced runtime

**Disposition:** keep (with targeted changes)
**Layer:** concept

**Concept:** Three async workers — LLM, tool, circuit-breaker — subscribe to one typed per-session event stream and produce autonomous agent behavior by reacting to each other's events. No orchestrator, no direct coupling.

**Current realization:**

- `harness_poc/core/processors/processor_supervisor.py` — `ProcessorSupervisor` owns the three `asyncio.Task`s and tracks in-flight skill calls for cancellation.
- `harness_poc/core/processors/llm_worker.py` — `run_llm_worker`: runs the model, parses JSON tool-call requests, emits `LLMActionEmitted` + `SkillRequested` or `LLMTextEmitted`. Also extracts `[entry:<id>]` citation markers into `MapEntryReferenced` events.
- `harness_poc/core/processors/tool_worker.py` — `run_skill_worker`: dispatches `SkillRequested` to `SkillRunner`, converts exceptions to `failed`-status `SkillCompleted` events.
- `harness_poc/core/processors/circuit_breaker.py` — `run_circuit_breaker`: tallies tokens and consecutive failures, emits `StreamPaused` on breach.
- `harness_poc/core/events/event_bus.py` — async pub/sub via `subscribe_session(session_id)`.
- `harness_poc/core/events/event_store.py` — durable Pydantic-event persistence.
- `harness_poc/core/events/events.py` — typed event registry (`AgentInputAdded`, `SkillRequested`, `SkillCompleted`, `LLMActionEmitted`, `LLMTextEmitted`, `StreamPaused`, …).

**Why keep:**

- **Decoupling is the deliverable.** Workers know event types, not each other. Adding a new subscriber (recorder, observability tap, second model) costs zero edits to existing code. **Replayable by construction.** The `AgentInputAdded → LLMActionEmitted + SkillRequested → SkillCompleted` chain carries enough structure to rebuild any session from the event log. Tool calls travel as data, not provider API artifacts.
- **Autonomy lives in one filter clause.** `llm_worker.py:54` subscribes to both `AgentInputAdded` _and_ `SkillCompleted`. That single line is the entire ReAct loop — no while-loop, no orchestrator state machine.
- **`StreamPaused` as a kill switch.** A single event halts every worker. Clean shutdown semantics, easy to extend with new termination reasons.
- **Failure stays inside the event model.** Skill exceptions convert to `failed`-status `SkillCompleted` (`tool_worker.py:66`). The runtime never crashes; the next LLM iteration sees the failure and can react to it.

**What to change:**

- **Decide JSON-in-content vs. native tool-calls deliberately.** Today the LLM worker disables PydanticAI tools (`enable_tools=False`) and parses `{"skill_name", "arguments"}` from the model's text content. Great for replayability, brittle on model-quality drift. Pick one path — keep and harden parsing, or use native tool-calls + a recorder that mirrors them as events.
- **Asymmetric shutdown.** `StreamPaused` is the documented kill switch, but `ProcessorSupervisor.stop()` cancels tasks without publishing it. Either route every shutdown through `StreamPaused`, or stop calling it the sole termination signal.
- **Delete the legacy duplicate fields.** `SkillCompleted` carries both `tool_name`/`skill_name` and `content`/`result` with a `model_validator` copying between them (`events.py:51`). `LLMActionEmitted` does the same with `tokens_used`/`new_tokens`/`billable_tokens`. Pick one name per concept.
- **Drop legacy `SkillCalled`.** Tool worker still accepts both `SkillCalled` and `SkillRequested` (`tool_worker.py:32`). Collapse to one event.
- **Split context-map citation extraction out of the LLM worker.** `_extract_references` is ~100 lines of context-map plumbing living inside the worker. Move it to its own subscriber that reads `LLMTextEmitted`. Worker should be single-purpose.
- **Add event schema versioning.** Events are Pydantic models with no version field — the compat validators above prove a breaking change is already overdue. Stamp `schema_version` on `BaseEvent` before the next change.
- **Reconsider scoping primitive.** `subscribe_session(session_id)` is the only filter. Fine for one user, but project + session + corpus may be the right scoping triple for multi-tenant.

**Depends on:**

- `EventBus` + `EventStore` (own keeper).
- Typed event registry (`core/events/events.py`) (own keeper).
- `SkillRunner` (separately captured under the skills system).
- `PydanticAgentRuntime` (LLM client wrapper) (own keeper).

**ACDL status:** needs spec — the per-worker event contracts (what each consumes, what each produces) and the loop termination conditions are exactly the kind of thing ACDL should pin down before re-implementation.

**Tested via:** `tests/runtime/test_tool_worker.py`, `tests/unit/test_circuit_breaker.py`.

**Notes:**

- A parallel `GoalRunner` path (`core/runtime/goal_runner.py`) still exists for some flows during migration. The rewrite should pick **one** — the event-sourced path is the strategic direction.
- Preserve the "autonomy is one filter clause" property in any ACDL spec and any future docs. It is the architectural punchline of this design.

---

### Context map (PEEK)

_TBD_

---

### SOUL / pedagogy setup

_TBD_

---

### Self-introspection skills

_TBD_

---

### ACDL as the standard language

_TBD_

## Consciously dropped / deferred

| Component | Disposition | Why |
| --------- | ----------- | --- |
|           |             |     |
