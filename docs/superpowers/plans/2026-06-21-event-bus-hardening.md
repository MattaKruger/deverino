# Event Bus Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden the event bus backbone by fixing a correctness bug, eliminating dead code, and adding backpressure protection.

**Architecture:** Three files, nine targeted changes. All changes are backward-compatible — no public API surfaces are removed that have callers. Callsite analysis confirmed: `publish()` is never awaited (all async callers use `publish_async()`), `subscribe()` is always called with `(EventType, handler)` form, and `BaseEvent.timestamp` has no readers.

**Tech Stack:** Python 3.14, Pydantic v2, SQLAlchemy/SQLModel, asyncio.

## Global Constraints

- Run tests with `uv run pytest`; lint with `uv run ruff check .`; types with `uv run ty check`
- Line length = 100, double quotes
- Tests must be deterministic — no real network or model calls
- Tests use SQLite (fixture: `db_engine`)
- Commit after each task

---

## File Map

| File | Changes |
|---|---|
| `harness_poc/core/events/event_store.py` | Fix except syntax bug; drop `session.refresh()`; inline lazy import |
| `harness_poc/core/events/event_bus.py` | Drop `_Published`; drop dead `_queue`; simplify `subscribe()`; inline `_subscribe_session`; add subscriber queue `maxsize` |
| `harness_poc/core/events/events.py` | Drop `BaseEvent.timestamp` duplicate field |
| `tests/event/test_event_store.py` | Add test for malformed payload skip |
| `harness_poc/v2/tests/test_event_bus.py` | Add tests for `publish()→None`, handler-only `subscribe()`, queue-full warning |
| `tests/unit/test_events.py` | Add test that `timestamp` field is gone |

---

### Task 1: Harden `event_store.py`

Three independent fixes in one file. The syntax bug (`except ValueError, KeyError:` is Python 2 — in Python 3 it silently becomes `except ValueError as KeyError:`, shadowing the `KeyError` builtin and leaving `KeyError` exceptions unhandled). The `session.refresh(row)` fires an extra SELECT after every persist unnecessarily — SQLAlchemy populates the PK after commit without it. The `_DbStateEvent()` helper produces confusing double-call syntax `_DbStateEvent()()`.

**Files:**
- Modify: `harness_poc/core/events/event_store.py`
- Modify: `tests/event/test_event_store.py`

**Interfaces:**
- Produces: `EventStore` with identical public API, `.persist()` and `.get_recent_events()` unchanged

- [ ] **Step 1: Write a failing test for the malformed-payload skip**

Add to `tests/event/test_event_store.py`:

```python
def test_skips_malformed_event_payload_and_continues(db_engine: Engine) -> None:
    from datetime import UTC, datetime

    from harness_poc.core.storage import DbStateEvent

    store = _make_store(db_engine)
    # Inject a row with a known event_type but missing required fields in payload
    with Session(db_engine) as session:
        session.add(
            DbStateEvent(
                scope="session",
                scope_id="s2",
                event_type="SkillCalled",
                payload={"event_type": "SkillCalled", "payload": {"session_id": "s2"}},
                created_at=datetime.now(tz=UTC).isoformat(timespec="seconds"),
            )
        )
        session.commit()

    store.persist(SkillCalled(session_id="s2", tool_name="good_skill", arguments={}))
    events = store.get_recent_events("s2")
    assert len(events) == 1
    assert isinstance(events[0], SkillCalled)
    assert events[0].tool_name == "good_skill"
```

- [ ] **Step 2: Run the test — expect failure**

```bash
uv run pytest tests/event/test_event_store.py::test_skips_malformed_event_payload_and_continues -v
```

Expected: FAIL — the malformed row either raises or corrupts deserialization (the except clause doesn't catch correctly due to the syntax bug).

- [ ] **Step 3: Fix `event_store.py` — all three changes**

Replace the entire file content with:

```python
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from sqlmodel import Session, col, select

if TYPE_CHECKING:
    from sqlalchemy import Engine

    from harness_poc.core.events.events import BaseEvent

from harness_poc.core.events.events import EVENT_REGISTRY
from harness_poc.core.observe import current_trace


logger = logging.getLogger(__name__)


class EventStore:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @property
    def engine(self) -> Engine:
        return self._engine

    def persist(self, event: BaseEvent) -> None:
        from harness_poc.core.storage import DbStateEvent  # noqa: PLC0415

        payload = {
            "event_type": event.event_type,
            "payload": event.model_dump(mode="json"),
        }
        with Session(self._engine) as session:
            row = DbStateEvent(
                scope="session",
                scope_id=event.session_id,
                event_type=event.event_type,
                payload=payload,
                created_at=event.created_at.isoformat(timespec="seconds"),
            )
            session.add(row)
            session.commit()
            # PK is populated after commit; refresh() was an unnecessary extra SELECT
            event.id = row.id or 0
            trace = current_trace()
            logger.debug(
                "Persisted event: %s (session=%s)",
                type(event).__name__,
                getattr(event, "session_id", "?"),
                extra=trace.as_extra() if trace else None,
            )

    async def persist_async(self, event: BaseEvent) -> None:
        await asyncio.to_thread(self.persist, event)

    def get_recent_events(
        self,
        session_id: str,
        limit: int = 20,
        event_types: list[type[BaseEvent]] | None = None,
    ) -> list[BaseEvent]:
        from harness_poc.core.storage import DbStateEvent  # noqa: PLC0415

        type_names = [t.__name__ for t in event_types] if event_types is not None else None
        with Session(self._engine) as session:
            stmt = (
                select(DbStateEvent)
                .where(DbStateEvent.scope == "session")
                .where(DbStateEvent.scope_id == session_id)
            )
            if type_names:
                stmt = stmt.where(col(DbStateEvent.event_type).in_(type_names))
            stmt = stmt.order_by(col(DbStateEvent.id).desc()).limit(limit)
            rows = session.exec(stmt).all()

        events: list[BaseEvent] = []
        for row in rows:
            try:
                outer = row.payload
                event_type_name = str(outer.get("event_type", ""))
                event_cls = EVENT_REGISTRY.get(event_type_name)
                if event_cls is None:
                    logger.warning("Unknown event_type in store, skipping: %s", event_type_name)
                    continue
                evt = event_cls.model_validate(outer["payload"])
                evt.id = row.id or 0
                events.append(evt)
            except (ValueError, KeyError):
                logger.warning("Skipping malformed event row", exc_info=True)

        events.reverse()
        return events
```

Key changes from original:
1. `except (ValueError, KeyError):` — parentheses added (Python 3 tuple syntax)
2. `session.refresh(row)` removed — PK available after `commit()` without it
3. `_DbStateEvent()` helper function dropped — import inlined at the two use sites

- [ ] **Step 4: Run the test — expect pass**

```bash
uv run pytest tests/event/test_event_store.py -v
```

Expected: all tests PASS including the new malformed-payload test.

- [ ] **Step 5: Lint**

```bash
uv run ruff check harness_poc/core/events/event_store.py
```

Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add harness_poc/core/events/event_store.py tests/event/test_event_store.py
git commit -m "fix: harden event_store — except tuple syntax, drop redundant refresh, inline lazy import"
```

---

### Task 2: Simplify and harden `event_bus.py`

Five changes:

1. **Drop `_Published`** — a custom awaitable returned by `publish()` so callers could `await bus.publish()`. Callsite analysis shows zero callers await it; all async callers already use `publish_async()`. Return `None` instead.
2. **Drop dead `self._queue`** — an `asyncio.Queue` created in `__init__` but never read, just accumulated events forever. Silent memory leak.
3. **Simplify `subscribe()`** — the overloaded union signature handles two unrelated things (handler registration and async generator subscription). All 25+ callsites use `subscribe(EventType, handler)`. The session-id path is only reached via `subscribe_session()` directly. Drop the union; keep handler-only.
4. **Inline `_subscribe_session`** — private method aliased by `subscribe_session`. Merge them.
5. **Add `maxsize=500` to subscriber queues** — `asyncio.Queue()` is unbounded by default. A slow or stuck subscriber grows without limit. Catch `QueueFull` in `_dispatch` and log a warning.

**Files:**
- Modify: `harness_poc/core/events/event_bus.py`
- Modify: `harness_poc/v2/tests/test_event_bus.py`

**Interfaces:**
- `publish(event) -> None` (was `-> _Published`)
- `subscribe(event_type, handler) -> None` (no more overload; session-id string form removed)
- `subscribe_session(session_id) -> AsyncGenerator[BaseEvent]` (unchanged)
- `unsubscribe`, `get_recent_events`, `publish_async` — unchanged

- [ ] **Step 1: Write three failing tests**

Add to `harness_poc/v2/tests/test_event_bus.py`, inside the `TestEventBusPublish` class:

```python
def test_publish_returns_none(self):
    bus = _make_bus()
    result = bus.publish(AgentInputAdded(session_id="s", user_content="x"))
    assert result is None
```

Add a new test class after `TestEventBusUnsubscribe`:

```python
class TestEventBusSubscribeHandlerOnly:
    """subscribe() accepts only (event_type, handler) after overload removal."""

    def test_subscribe_string_raises_type_error(self):
        bus = _make_bus()
        with pytest.raises(TypeError):
            bus.subscribe("some-session-id")  # type: ignore[call-arg]

    def test_dispatch_warns_and_does_not_raise_on_full_queue(self, caplog):
        import logging

        bus = _make_bus()
        # Manually seed a pre-filled queue to simulate a slow subscriber
        full_queue: asyncio.Queue = asyncio.Queue(maxsize=1)
        full_queue.put_nowait(AgentInputAdded(session_id="x", user_content="pre-fill"))
        bus._async_subscribers.append(full_queue)

        with caplog.at_level(logging.WARNING):
            bus.publish(AgentInputAdded(session_id="x", user_content="overflow"))

        assert "queue full" in caplog.text.lower()
        assert full_queue.qsize() == 1  # overflow was dropped, not enqueued
        bus._async_subscribers.remove(full_queue)
```

- [ ] **Step 2: Run tests — expect failures**

```bash
uv run pytest harness_poc/v2/tests/test_event_bus.py::TestEventBusPublish::test_publish_returns_none harness_poc/v2/tests/test_event_bus.py::TestEventBusSubscribeHandlerOnly -v
```

Expected: FAIL — `publish()` currently returns `_Published()` not `None`; `subscribe("string")` currently succeeds; `_dispatch` currently raises on full queue.

- [ ] **Step 3: Replace `event_bus.py`**

```python
from __future__ import annotations

import asyncio
import contextlib
import logging
from collections import defaultdict
from typing import TYPE_CHECKING, Any, TypeVar

from harness_poc.core.events.events import BaseEvent
from harness_poc.core.observe import current_trace

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable

    from harness_poc.core.events.event_store import EventStore

logger = logging.getLogger(__name__)

E = TypeVar("E", bound=BaseEvent)


class EventBus:
    def __init__(self, event_store: EventStore) -> None:
        self._store: EventStore = event_store
        self._handlers: dict[str, list[Callable[[Any], None]]] = defaultdict(list)
        self._async_subscribers: list[asyncio.Queue[BaseEvent]] = []

    def publish(self, event: BaseEvent) -> None:
        self._store.persist(event)
        self._dispatch(event)
        trace = current_trace()
        handlers = self._handlers.get(event.event_type, [])
        logger.debug(
            "Published event: %s (handlers=%d)",
            type(event).__name__,
            len(handlers),
            extra=trace.as_extra() if trace else None,
        )

    async def publish_async(self, event: BaseEvent) -> None:
        await self._store.persist_async(event)
        self._dispatch(event)

    def subscribe(self, event_type: type[E], handler: Callable[[E], None]) -> None:
        self._handlers[event_type.__name__].append(handler)  # type: ignore[arg-type]

    def unsubscribe(self, event_type: type[E], handler: Callable[[E], None]) -> None:
        with contextlib.suppress(ValueError):
            self._handlers[event_type.__name__].remove(handler)  # type: ignore[arg-type]

    async def subscribe_session(self, session_id: str) -> AsyncGenerator[BaseEvent]:
        # ponytail: maxsize=500 caps memory per slow subscriber; QueueFull drops events with a warning
        queue: asyncio.Queue[BaseEvent] = asyncio.Queue(maxsize=500)
        self._async_subscribers.append(queue)
        try:
            while True:
                event = await queue.get()
                if event.session_id == session_id:
                    yield event
        finally:
            with contextlib.suppress(ValueError):
                self._async_subscribers.remove(queue)

    def get_recent_events(
        self,
        session_id: str,
        limit: int = 20,
        event_types: list[type[BaseEvent]] | None = None,
    ) -> list[BaseEvent]:
        return self._store.get_recent_events(
            session_id=session_id,
            limit=limit,
            event_types=event_types,
        )

    def _dispatch(self, event: BaseEvent) -> None:
        for subscriber in list(self._async_subscribers):
            try:
                subscriber.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning(
                    "Subscriber queue full, dropping event: %s", type(event).__name__
                )

        for handler in list(self._handlers.get(event.event_type, [])):
            try:
                handler(event)
            except Exception:
                logger.exception("Event handler raised for %s", event.event_type)
```

Changes from original:
1. `_Published` class removed; `publish()` returns `None`
2. `self._queue` field removed from `__init__`; `self._queue.put_nowait(event)` removed from `_dispatch`
3. `subscribe()` simplified to single-signature handler-only; overloads and union type removed
4. `_subscribe_session()` private method removed; body merged into `subscribe_session()` directly
5. `asyncio.Queue(maxsize=500)` with `QueueFull` catch and warning in `_dispatch`
6. Import cleanup: removed `overload`, `Generator` (no longer needed)

- [ ] **Step 4: Run all event bus tests**

```bash
uv run pytest harness_poc/v2/tests/test_event_bus.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Run full test suite to catch regressions**

```bash
uv run pytest tests/ -v --tb=short -q
```

Expected: no new failures. If `subscribe()` call with session_id string fails anywhere, search with `grep -rn "\.subscribe(" harness_poc/ --include="*.py"` — all found callers use `(EventType, handler)` form, so this should be clean.

- [ ] **Step 6: Lint**

```bash
uv run ruff check harness_poc/core/events/event_bus.py
```

Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add harness_poc/core/events/event_bus.py harness_poc/v2/tests/test_event_bus.py
git commit -m "fix: harden event_bus — drop _Published, dead queue, simplify subscribe, add subscriber backpressure"
```

---

### Task 3: Drop `BaseEvent.timestamp`

`BaseEvent` has two datetime fields both set to `datetime.now(UTC)`: `timestamp` (line 14) and `created_at` (line 15). They diverge by nanoseconds at construction, and `created_at` is the one used everywhere. `timestamp` has no callers in the codebase (verified by grep — the `database.py` `.timestamp` usage is on `ContextMapEvent`, a different class). Old events in the DB that have `timestamp` in their payload will still deserialize fine — Pydantic ignores extra fields by default.

**Files:**
- Modify: `harness_poc/core/events/events.py`
- Modify: `tests/unit/test_events.py`

**Interfaces:**
- `BaseEvent` loses `timestamp` field; all other fields and behavior unchanged

- [ ] **Step 1: Write a failing test**

Add to `tests/unit/test_events.py`:

```python
def test_base_event_has_no_timestamp_field():
    """timestamp was a duplicate of created_at; only created_at remains."""
    assert "timestamp" not in BaseEvent.model_fields
    assert "created_at" in BaseEvent.model_fields
```

- [ ] **Step 2: Run it — expect failure**

```bash
uv run pytest tests/unit/test_events.py::test_base_event_has_no_timestamp_field -v
```

Expected: FAIL — `timestamp` is currently in `model_fields`.

- [ ] **Step 3: Remove the `timestamp` field from `BaseEvent`**

In `harness_poc/core/events/events.py`, remove line 14:

```python
# Remove this line:
timestamp: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))
```

The `BaseEvent` block should become:

```python
class BaseEvent(BaseModel):
    id: int | None = None
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))
    type_name: str = ""

    @model_validator(mode="after")
    def _populate_type_name(self) -> BaseEvent:
        if not self.type_name:
            self.type_name = self.__class__.__name__
        return self

    @property
    def event_type(self) -> str:
        return self.__class__.__name__
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/unit/test_events.py -v
```

Expected: all tests PASS including `test_base_event_has_no_timestamp_field`.

- [ ] **Step 5: Run full test suite**

```bash
uv run pytest tests/ harness_poc/v2/tests/ -q --tb=short
```

Expected: no failures. If anything fails with `AttributeError: 'X' object has no attribute 'timestamp'`, that caller needs updating (unexpected — grep found none).

- [ ] **Step 6: Lint and types**

```bash
uv run ruff check harness_poc/core/events/events.py && uv run ty check
```

Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add harness_poc/core/events/events.py tests/unit/test_events.py
git commit -m "fix: drop BaseEvent.timestamp duplicate field, created_at is canonical"
```

---

## Out of Scope (noted for future work)

These were identified in the ponytail review but excluded here:

- **`event_type`/`type_name` consolidation** — 15+ callsites across 10 files; both names serve active callers. Separate refactor.
- **`SkillCompleted.skill_name` + `result` compat fields** — `skill_name` is a primary field actively used throughout tool_worker, llm_worker, tests, dashboard. Not dead code.
- **`LLMActionEmitted.new_tokens`/`billable_tokens`** — primary fields used for token accounting throughout; not aliases.
- **`order_by(desc) + reverse()`** — semantically correct (most-recent N in chronological order); a naive `order_by(asc)` would return the oldest N instead.
