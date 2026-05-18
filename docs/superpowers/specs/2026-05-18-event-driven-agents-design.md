# Event-Driven Agents Design

**Date:** 2026-05-18
**Status:** approved
**Author:** Matthijs Kruger

## Problem

The current `GoalRunner` and `BlackboardDatabase` are tightly coupled through direct method calls (`record_llm_action`, `record_tool_observation`, `get_recent_events`). Sub-agent coordination via `delegate_task` is blocking and invisible — callers have no way to observe, intercept, or react to agent lifecycle events. There is no pub/sub mechanism, so multi-agent workflows cannot be composed without hardcoding orchestration logic in the skill or runner.

The goal is to introduce a typed event bus as the foundational primitive for agent communication, observability, and future async coordination — without a full rewrite of the system.

## Goals

- **Multi-agent coordination**: agents publish events when they start, call skills, and complete; other agents/orchestrators can subscribe and react.
- **Observability / replay**: a typed, structured event log that captures everything each agent does, queryable for debugging and context-window reconstruction.
- **Async-readiness**: synchronous in-process delivery now; structured so async dispatch (asyncio queue, worker threads) can be dropped in later without changing callers.
- **Replace direct DB coupling**: remove `record_llm_action`, `record_tool_observation`, `get_recent_events` from `BlackboardDatabase`; all agent event writes go through the bus.

## Non-Goals

- True async execution in this pass (no threads, no asyncio event loop changes).
- Replacing snapshot state tables (`project_state`, `session_state`, `shared_memory`, `state_proposals`) — those remain untouched.
- Full event-sourcing / projection-based state (a natural next step after this design is proven).
- Wiring `SubAgentDispatched` / `SubAgentCompleted` into `delegate_task` skill internals (events are defined and emittable; full wiring is a follow-up).

## Architecture

### New Modules

| Module | Responsibility |
|---|---|
| `harness_poc/core/events.py` | Typed Pydantic event hierarchy |
| `harness_poc/core/event_store.py` | SQLite persistence for events; owns `state_events` table |
| `harness_poc/core/event_bus.py` | In-process pub/sub; dispatches to subscribers and persists |

### Modified Files

| File | Change |
|---|---|
| `harness_poc/core/database.py` | Remove `record_llm_action`, `record_tool_observation`, `get_recent_events`, `_insert_state_event`; `EventStore` fully owns `state_events` — `BlackboardDatabase` no longer writes to that table |
| `harness_poc/core/goal_runner.py` | Publish events via `EventBus` instead of direct DB calls |
| `harness_poc/app_factory.py` | Add `event_bus: EventBus` to `AppState`; wire into `GoalRunner` |
| `harness_poc/core/pydantic_runtime.py` | No changes in this pass — the REPL/pydantic chat path does not emit bus events; events only flow through `GoalRunner`-driven loops |
| `tests/test_goal_runner.py` | Replace DB mock with `RecordingEventBus` stub |

## Event Schema

### Base

```python
class BaseEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))

    @property
    def event_type(self) -> str:
        return self.__class__.__name__
```

### Concrete Events

```python
class AgentStarted(BaseEvent):
    goal: str

class SkillCalled(BaseEvent):
    tool_name: str
    arguments: dict[str, Any]

class SkillCompleted(BaseEvent):
    tool_name: str
    status: str           # "success" | "error" | "blocked"
    content: str
    artifacts: dict[str, Any] = Field(default_factory=dict)

class GoalEvaluated(BaseEvent):
    is_complete: bool
    reasoning: str
    final_answer: str = ""

class LLMTextEmitted(BaseEvent):
    content: str

class SubAgentDispatched(BaseEvent):
    sub_session_id: str
    persona: str
    objective: str

class SubAgentCompleted(BaseEvent):
    sub_session_id: str
    status: str
    content: str
```

### Storage Format

`EventStore` serializes each event as:
```json
{"event_type": "SkillCalled", "payload": { ... }}
```
into the existing `state_events.payload` column. Deserialization uses a registry `dict[str, type[BaseEvent]]` keyed by `event_type` — no `if/elif` chains.

## EventBus API

```python
class EventBus:
    def publish(self, event: BaseEvent) -> None:
        # 1. Persist to EventStore (hard failure if this fails)
        # 2. Dispatch to registered subscribers synchronously
        # 3. Catch subscriber exceptions individually — log, continue

    def subscribe(self, event_type: type[E], handler: Callable[[E], None]) -> None:
        # Register handler for a specific event type

    def get_recent_events(
        self,
        session_id: str,
        limit: int = 20,
        event_types: list[type[BaseEvent]] | None = None,
    ) -> list[BaseEvent]:
        # Read from EventStore, optional type filter, chronological order
```

**Async upgrade path**: swap the synchronous handler loop in `publish()` for `asyncio.create_task()` or a queue. Callers and event schema are unchanged.

## Data Flow

```
GoalRunner.run(goal, app_state)
  │
  ├─ bus.publish(AgentStarted(session_id, goal))
  │
  └─ [each iteration]
       ├─ bus.get_recent_events(session_id, limit=20,
       │       event_types=[SkillCalled, SkillCompleted, GoalEvaluated, LLMTextEmitted])
       ├─ _build_messages(goal, events)
       ├─ _decide_next_action(...)
       │
       ├─ [tool call path]
       │    ├─ bus.publish(SkillCalled(tool_name, arguments))
       │    ├─ skill_runner.execute_skill(...)
       │    └─ bus.publish(SkillCompleted(tool_name, status, content, artifacts))
       │
       ├─ [evaluate_goal intercept]
       │    └─ bus.publish(GoalEvaluated(is_complete, reasoning, final_answer))
       │
       └─ [_llm_text path]
            └─ bus.publish(LLMTextEmitted(content))
```

`_build_messages` receives `list[BaseEvent]` instead of `list[StateEvent]`. The formatting function `_format_event_for_prompt` dispatches on the typed event class (not a string field).

## Error Handling

- **`EventStore.persist`**: wraps the SQLite write; on failure logs and re-raises. A failed persist is a hard error — losing an event silently breaks observability.
- **`EventBus.publish`**: persists first (may raise), then dispatches to subscribers. Each subscriber is called inside its own try/except; a bad handler logs and continues — remaining subscribers still run.
- **`EventStore.get_recent_events`**: on a corrupted/unrecognized row, logs a warning and skips that row rather than crashing context window build.

## Testing

- **Unit tests for `EventBus` + `EventStore`**: use SQLite `:memory:` — no mocking, fast.
- **`RecordingEventBus` stub**: collects published events in a list, no persistence. Used in `test_goal_runner.py` to assert event sequences without disk I/O.
- **Updated `test_goal_runner.py`**: pass `RecordingEventBus` into `GoalRunner`; assert correct event types and order.
- **Integration test**: run a short goal loop end-to-end, call `bus.get_recent_events()`, assert expected sequence (`AgentStarted` → `SkillCalled` → `SkillCompleted` → `GoalEvaluated`).

## Migration Notes

The `state_events` table schema is unchanged — existing rows remain readable. New rows written by `EventStore` use the same columns; the `payload` column format changes from the ad-hoc `{"tool_name": ..., "arguments": ...}` dict to `{"event_type": "SkillCalled", "payload": {...}}`. Old rows written before migration are skipped during deserialization (unrecognized format → warning + skip).
