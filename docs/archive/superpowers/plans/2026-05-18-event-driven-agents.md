# Event-Driven Agents Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace direct `BlackboardDatabase` event calls with a typed `EventBus` as the single source of truth for agent execution events.

**Architecture:** Three new modules (`events.py`, `event_store.py`, `event_bus.py`) replace scattered `record_llm_action` / `record_tool_observation` / `get_recent_events` calls. `GoalRunner` publishes typed Pydantic events to an `EventBus`; `AppState` carries the bus. All tests stay green; no existing snapshot tables (`project_state`, `session_state`, etc.) are touched.

**Tech Stack:** Python 3.12, Pydantic v2 (`BaseModel`, `model_dump`, `model_validate`), SQLite (existing `state_events` table), pytest with `:memory:` / temp-file SQLite.

**Spec:** `docs/superpowers/specs/2026-05-18-event-driven-agents-design.md`

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Create | `harness_poc/core/events.py` | Typed Pydantic event hierarchy + registry |
| Create | `harness_poc/core/event_store.py` | SQLite persistence for events |
| Create | `harness_poc/core/event_bus.py` | In-process pub/sub dispatcher |
| Create | `tests/helpers.py` | `RecordingEventBus` test stub |
| Create | `tests/test_events.py` | Event schema unit tests |
| Create | `tests/test_event_store.py` | EventStore unit tests |
| Create | `tests/test_event_bus.py` | EventBus unit tests |
| Modify | `harness_poc/app_factory.py` | Add `event_bus: EventBus` to `AppState`; wire in `build_app_state` |
| Modify | `harness_poc/core/goal_runner.py` | Publish typed events via bus; remove DB event calls |
| Modify | `harness_poc/core/database.py` | Remove `record_llm_action`, `record_tool_observation`, `get_recent_events` |
| Modify | `tests/test_goal_runner.py` | Replace DB event assertions with bus assertions; remove dead DB tests |

---

## Task 1: Typed event hierarchy

**Files:**
- Create: `harness_poc/core/events.py`
- Create: `tests/test_events.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_events.py
from __future__ import annotations

from harness_poc.core.events import (
    AgentStarted,
    EVENT_REGISTRY,
    GoalEvaluated,
    LLMTextEmitted,
    SkillCalled,
    SkillCompleted,
    SubAgentCompleted,
    SubAgentDispatched,
)


def test_event_type_property_matches_class_name() -> None:
    event = SkillCalled(session_id="s1", tool_name="foo", arguments={})
    assert event.event_type == "SkillCalled"


def test_base_event_auto_generates_unique_ids() -> None:
    e1 = AgentStarted(session_id="s1", goal="g")
    e2 = AgentStarted(session_id="s1", goal="g")
    assert e1.event_id != e2.event_id


def test_event_registry_covers_all_concrete_types() -> None:
    expected = {
        "AgentStarted", "SkillCalled", "SkillCompleted", "GoalEvaluated",
        "LLMTextEmitted", "SubAgentDispatched", "SubAgentCompleted",
    }
    assert set(EVENT_REGISTRY.keys()) == expected


def test_skill_completed_round_trips_via_model_dump() -> None:
    event = SkillCompleted(
        session_id="s1",
        tool_name="read_memory",
        status="success",
        content="data",
        artifacts={"k": "v"},
    )
    d = event.model_dump()
    restored = SkillCompleted.model_validate(d)
    assert restored.tool_name == "read_memory"
    assert restored.artifacts == {"k": "v"}
    assert restored.event_id == event.event_id


def test_goal_evaluated_default_final_answer_is_empty() -> None:
    event = GoalEvaluated(session_id="s1", is_complete=True, reasoning="done")
    assert event.final_answer == ""
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_events.py -v
```
Expected: `ImportError` — `harness_poc.core.events` does not exist yet.

- [ ] **Step 3: Implement `harness_poc/core/events.py`**

```python
# harness_poc/core/events.py
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


class BaseEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))

    @property
    def event_type(self) -> str:
        return self.__class__.__name__


class AgentStarted(BaseEvent):
    goal: str


class SkillCalled(BaseEvent):
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class SkillCompleted(BaseEvent):
    tool_name: str
    status: str
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


EVENT_REGISTRY: dict[str, type[BaseEvent]] = {
    cls.__name__: cls  # type: ignore[misc]
    for cls in [
        AgentStarted,
        SkillCalled,
        SkillCompleted,
        GoalEvaluated,
        LLMTextEmitted,
        SubAgentDispatched,
        SubAgentCompleted,
    ]
}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_events.py -v
```
Expected: 5 tests PASS.

- [ ] **Step 5: Lint and type-check**

```bash
uv run ruff check harness_poc/core/events.py tests/test_events.py
uv run ty check
```
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add harness_poc/core/events.py tests/test_events.py
git commit -m "feat: add typed event hierarchy for event-driven agents"
```

---

## Task 2: EventStore

**Files:**
- Create: `harness_poc/core/event_store.py`
- Create: `tests/test_event_store.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_event_store.py
from __future__ import annotations

import sqlite3
import tempfile

from harness_poc.core.event_store import EventStore
from harness_poc.core.events import AgentStarted, SkillCalled, SkillCompleted


def _make_store() -> EventStore:
    """EventStore backed by a temp SQLite file with the state_events table."""
    tf = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    db_path = tf.name
    tf.close()
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS state_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scope TEXT NOT NULL,
            scope_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            payload TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()
    return EventStore(db_path)


def test_persist_and_retrieve_single_event() -> None:
    store = _make_store()
    event = SkillCalled(session_id="s1", tool_name="read_memory", arguments={"key": "x"})
    store.persist(event)
    events = store.get_recent_events("s1")
    assert len(events) == 1
    assert isinstance(events[0], SkillCalled)
    assert events[0].tool_name == "read_memory"
    assert events[0].arguments == {"key": "x"}


def test_get_recent_events_respects_limit() -> None:
    store = _make_store()
    for i in range(5):
        store.persist(SkillCalled(session_id="s1", tool_name=f"skill_{i}", arguments={}))
    events = store.get_recent_events("s1", limit=3)
    assert len(events) == 3
    assert events[-1].tool_name == "skill_4"  # most recent last


def test_get_recent_events_type_filter() -> None:
    store = _make_store()
    store.persist(AgentStarted(session_id="s1", goal="g"))
    store.persist(SkillCalled(session_id="s1", tool_name="foo", arguments={}))
    store.persist(SkillCompleted(session_id="s1", tool_name="foo", status="success", content="ok"))
    events = store.get_recent_events("s1", event_types=[SkillCalled, SkillCompleted])
    assert len(events) == 2
    assert all(isinstance(e, (SkillCalled, SkillCompleted)) for e in events)


def test_get_recent_events_returns_chronological_order() -> None:
    store = _make_store()
    store.persist(SkillCalled(session_id="s1", tool_name="first", arguments={}))
    store.persist(SkillCalled(session_id="s1", tool_name="second", arguments={}))
    events = store.get_recent_events("s1")
    assert events[0].tool_name == "first"
    assert events[1].tool_name == "second"


def test_skips_unrecognized_event_type_and_continues() -> None:
    store = _make_store()
    # Inject a legacy row directly
    conn = sqlite3.connect(store.database_path)
    conn.execute(
        "INSERT INTO state_events (scope, scope_id, event_type, payload, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        ("session", "s1", "OldLegacyEvent", '{"tool_name": "x"}', "2026-01-01T00:00:00"),
    )
    conn.commit()
    conn.close()
    store.persist(SkillCalled(session_id="s1", tool_name="bar", arguments={}))
    events = store.get_recent_events("s1")
    assert len(events) == 1
    assert isinstance(events[0], SkillCalled)
    assert events[0].tool_name == "bar"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_event_store.py -v
```
Expected: `ImportError` — `harness_poc.core.event_store` does not exist yet.

- [ ] **Step 3: Implement `harness_poc/core/event_store.py`**

```python
# harness_poc/core/event_store.py
from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

from harness_poc.core.events import BaseEvent, EVENT_REGISTRY

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class EventStore:
    def __init__(self, database_path: Path | str) -> None:
        self.database_path = Path(database_path)

    def persist(self, event: BaseEvent) -> None:
        payload = json.dumps(
            {"event_type": event.event_type, "payload": event.model_dump(mode="json")},
            sort_keys=True,
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO state_events (scope, scope_id, event_type, payload, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    "session",
                    event.session_id,
                    event.event_type,
                    payload,
                    event.created_at.isoformat(timespec="seconds"),
                ),
            )

    def get_recent_events(
        self,
        session_id: str,
        limit: int = 20,
        event_types: list[type[BaseEvent]] | None = None,
    ) -> list[BaseEvent]:
        type_names = [t.__name__ for t in event_types] if event_types is not None else None
        with self._connect() as conn:
            if type_names:
                placeholders = ",".join("?" * len(type_names))
                cursor = conn.execute(
                    f"""
                    SELECT payload FROM state_events
                    WHERE scope = 'session'
                      AND scope_id = ?
                      AND event_type IN ({placeholders})
                    ORDER BY id DESC
                    LIMIT ?
                    """,  # noqa: S608
                    (session_id, *type_names, limit),
                )
            else:
                cursor = conn.execute(
                    """
                    SELECT payload FROM state_events
                    WHERE scope = 'session'
                      AND scope_id = ?
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (session_id, limit),
                )
            rows = cursor.fetchall()

        events: list[BaseEvent] = []
        for row in rows:
            try:
                outer = json.loads(str(row["payload"]))
                event_type_name = outer.get("event_type", "")
                event_cls = EVENT_REGISTRY.get(event_type_name)
                if event_cls is None:
                    logger.warning("Unknown event_type in store, skipping: %s", event_type_name)
                    continue
                events.append(event_cls.model_validate(outer["payload"]))
            except Exception:
                logger.warning("Skipping malformed event row", exc_info=True)

        events.reverse()
        return events

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.database_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        return conn
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_event_store.py -v
```
Expected: 5 tests PASS.

- [ ] **Step 5: Lint and type-check**

```bash
uv run ruff check harness_poc/core/event_store.py tests/test_event_store.py
uv run ty check
```

- [ ] **Step 6: Commit**

```bash
git add harness_poc/core/event_store.py tests/test_event_store.py
git commit -m "feat: add EventStore for typed SQLite event persistence"
```

---

## Task 3: EventBus + RecordingEventBus test stub

**Files:**
- Create: `harness_poc/core/event_bus.py`
- Create: `tests/helpers.py`
- Create: `tests/test_event_bus.py`

- [ ] **Step 1: Create `tests/helpers.py` with `RecordingEventBus`**

```python
# tests/helpers.py
from __future__ import annotations

from typing import Any, Callable, TypeVar

from harness_poc.core.events import BaseEvent

E = TypeVar("E", bound=BaseEvent)


class RecordingEventBus:
    """In-memory EventBus for tests — no persistence, no subscribers."""

    def __init__(self) -> None:
        self.events: list[BaseEvent] = []

    def publish(self, event: BaseEvent) -> None:
        self.events.append(event)

    def subscribe(self, event_type: type[E], handler: Callable[[E], None]) -> None:
        pass

    def get_recent_events(
        self,
        session_id: str,
        limit: int = 20,
        event_types: list[type[BaseEvent]] | None = None,
    ) -> list[BaseEvent]:
        filtered = [e for e in self.events if e.session_id == session_id]
        if event_types is not None:
            names = {t.__name__ for t in event_types}
            filtered = [e for e in filtered if type(e).__name__ in names]
        return filtered[-limit:]
```

- [ ] **Step 2: Write failing tests**

```python
# tests/test_event_bus.py
from __future__ import annotations

import sqlite3
import tempfile
from unittest.mock import MagicMock

from harness_poc.core.event_bus import EventBus
from harness_poc.core.event_store import EventStore
from harness_poc.core.events import AgentStarted, SkillCalled, SkillCompleted
from tests.helpers import RecordingEventBus


# --- RecordingEventBus ---

def test_recording_bus_stores_published_events() -> None:
    bus = RecordingEventBus()
    event = AgentStarted(session_id="s1", goal="test goal")
    bus.publish(event)
    assert len(bus.events) == 1
    assert bus.events[0] is event


def test_recording_bus_filters_by_session() -> None:
    bus = RecordingEventBus()
    bus.publish(AgentStarted(session_id="s1", goal="g"))
    bus.publish(AgentStarted(session_id="s2", goal="g"))
    events = bus.get_recent_events("s1")
    assert len(events) == 1
    assert events[0].session_id == "s1"


def test_recording_bus_filters_by_event_type() -> None:
    bus = RecordingEventBus()
    bus.publish(AgentStarted(session_id="s1", goal="g"))
    bus.publish(SkillCalled(session_id="s1", tool_name="foo", arguments={}))
    events = bus.get_recent_events("s1", event_types=[SkillCalled])
    assert len(events) == 1
    assert isinstance(events[0], SkillCalled)


def test_recording_bus_respects_limit() -> None:
    bus = RecordingEventBus()
    for i in range(5):
        bus.publish(SkillCalled(session_id="s1", tool_name=f"s{i}", arguments={}))
    events = bus.get_recent_events("s1", limit=3)
    assert len(events) == 3
    assert events[-1].tool_name == "s4"


# --- EventBus with real EventStore ---

def _make_event_bus() -> EventBus:
    tf = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    db_path = tf.name
    tf.close()
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS state_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scope TEXT NOT NULL,
            scope_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            payload TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()
    return EventBus(EventStore(db_path))


def test_event_bus_publish_dispatches_to_subscriber() -> None:
    bus = _make_event_bus()
    handler = MagicMock()
    bus.subscribe(SkillCalled, handler)
    event = SkillCalled(session_id="s1", tool_name="foo", arguments={})
    bus.publish(event)
    handler.assert_called_once_with(event)


def test_event_bus_bad_handler_does_not_stop_other_handlers() -> None:
    bus = _make_event_bus()
    results: list[str] = []

    def bad_handler(_event: SkillCalled) -> None:
        raise RuntimeError("handler failure")

    def good_handler(event: SkillCalled) -> None:
        results.append(event.tool_name)

    bus.subscribe(SkillCalled, bad_handler)
    bus.subscribe(SkillCalled, good_handler)
    bus.publish(SkillCalled(session_id="s1", tool_name="foo", arguments={}))
    assert results == ["foo"]


def test_event_bus_get_recent_events_reads_from_store() -> None:
    bus = _make_event_bus()
    bus.publish(AgentStarted(session_id="s1", goal="g"))
    bus.publish(SkillCalled(session_id="s1", tool_name="foo", arguments={}))
    events = bus.get_recent_events("s1")
    assert len(events) == 2
    assert isinstance(events[0], AgentStarted)
    assert isinstance(events[1], SkillCalled)
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
uv run pytest tests/test_event_bus.py -v
```
Expected: `ImportError` for `event_bus` and `helpers`.

- [ ] **Step 4: Implement `harness_poc/core/event_bus.py`**

```python
# harness_poc/core/event_bus.py
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Callable, TypeVar

from harness_poc.core.event_store import EventStore
from harness_poc.core.events import BaseEvent

logger = logging.getLogger(__name__)

E = TypeVar("E", bound=BaseEvent)


class EventBus:
    def __init__(self, event_store: EventStore) -> None:
        self._store = event_store
        self._handlers: dict[str, list[Callable[[Any], None]]] = defaultdict(list)

    def publish(self, event: BaseEvent) -> None:
        self._store.persist(event)
        for handler in list(self._handlers.get(event.event_type, [])):
            try:
                handler(event)
            except Exception:
                logger.exception("Event handler raised for %s", event.event_type)

    def subscribe(self, event_type: type[E], handler: Callable[[E], None]) -> None:
        self._handlers[event_type.__name__].append(handler)  # type: ignore[arg-type]

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
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
uv run pytest tests/test_event_bus.py -v
```
Expected: 9 tests PASS.

- [ ] **Step 6: Lint and type-check**

```bash
uv run ruff check harness_poc/core/event_bus.py tests/helpers.py tests/test_event_bus.py
uv run ty check
```

- [ ] **Step 7: Commit**

```bash
git add harness_poc/core/event_bus.py tests/helpers.py tests/test_event_bus.py
git commit -m "feat: add EventBus with synchronous dispatch and RecordingEventBus test stub"
```

---

## Task 4: Wire EventBus into AppState

**Files:**
- Modify: `harness_poc/app_factory.py`

- [ ] **Step 1: Update `AppState` and `build_app_state`**

Replace the entire `harness_poc/app_factory.py` with:

```python
# harness_poc/app_factory.py
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import yaml

from harness_poc.core.config import HarnessConfig
from harness_poc.core.database import BlackboardDatabase
from harness_poc.core.event_bus import EventBus
from harness_poc.core.event_store import EventStore
from harness_poc.core.llm_client import LLMClient
from harness_poc.core.logging import configure_logging
from harness_poc.core.pydantic_runtime import (
    PydanticAgentRuntime,
    build_runtime,
)
from harness_poc.core.skill_runner import SkillRunner
from harness_poc.core.skill_scaffolder import SkillScaffolder
from harness_poc.core.state import build_state_context
from harness_poc.core.workflow_runner import WorkflowRunner

if TYPE_CHECKING:
    from pydantic_ai.messages import ModelMessage
    from pydantic_ai.models import Model

    from harness_poc.core.llm_client import Message


STARTUP_ERRORS = (
    OSError,
    RuntimeError,
    sqlite3.OperationalError,
    TypeError,
    ValueError,
    yaml.YAMLError,
)


@dataclass(slots=True)
class AppState:
    session_id: str
    database: BlackboardDatabase
    config: HarnessConfig
    skill_runner: SkillRunner
    skill_scaffolder: SkillScaffolder
    workflow_runner: WorkflowRunner
    llm_client: LLMClient
    pydantic_runtime: PydanticAgentRuntime
    pydantic_messages: list[ModelMessage]
    goal_decision_model: Model | None
    messages: list[Message]
    tools: list[dict[str, Any]]
    event_bus: EventBus


def build_app_state() -> AppState:
    config = HarnessConfig.load()
    configure_logging(config.project_root)
    database = BlackboardDatabase(config.runtime.database_path)
    database.create_tables()
    system_prompt = config.paths.soul.read_text(encoding="utf-8")
    session_id = database.start_session("Interactive proof of concept session.")
    project_state = database.ensure_project_state()
    session_state = database.ensure_session_state(session_id)
    skill_runner = SkillRunner(database=database, config=config)
    workflow_runner = WorkflowRunner(skill_runner)
    messages: list[Message] = [
        {
            "role": "system",
            "content": "\n\n".join(
                [
                    system_prompt,
                    build_state_context(project_state, session_state),
                ],
            ),
        },
    ]
    tools = skill_runner.discover_skills()
    full_system_prompt = "\n\n".join(
        [
            system_prompt,
            build_state_context(project_state, session_state),
        ],
    )
    event_store = EventStore(config.runtime.database_path)
    event_bus = EventBus(event_store)

    return AppState(
        session_id=session_id,
        database=database,
        config=config,
        skill_runner=skill_runner,
        skill_scaffolder=SkillScaffolder(config),
        workflow_runner=workflow_runner,
        llm_client=LLMClient(),
        pydantic_runtime=build_runtime(
            session_id=session_id,
            database=database,
            config=config,
            skill_runner=skill_runner,
            system_prompt=full_system_prompt,
            enable_tools=True,
        ),
        pydantic_messages=[],
        goal_decision_model=None,
        messages=messages,
        tools=tools,
        event_bus=event_bus,
    )
```

- [ ] **Step 2: Run full test suite to confirm nothing broke**

```bash
uv run pytest -v
```
Expected: all existing tests PASS (GoalRunner hasn't changed yet — it still calls `app_state.database.record_llm_action` etc., which still exist).

- [ ] **Step 3: Lint and type-check**

```bash
uv run ruff check harness_poc/app_factory.py
uv run ty check
```

- [ ] **Step 4: Commit**

```bash
git add harness_poc/app_factory.py
git commit -m "feat: add EventBus to AppState and wire in build_app_state"
```

---

## Task 5: Refactor GoalRunner to publish typed events

**Files:**
- Modify: `harness_poc/core/goal_runner.py`
- Modify: `tests/test_goal_runner.py`

- [ ] **Step 1: Update `harness_poc/core/goal_runner.py`**

Replace the file with the following. Key changes:
- Import `EventBus` types instead of `StateEvent`
- Publish `AgentStarted` at the top of `run()`
- `SkillCalled` replaces `record_llm_action` (only for real skills, not `evaluate_goal`)
- `SkillCompleted` replaces `record_tool_observation` (for skills and stuck detection)
- `GoalEvaluated` replaces the two `record_tool_observation` calls for `evaluate_goal` and its feedback
- `LLMTextEmitted` replaces the `record_tool_observation` for `_llm_text`
- `get_recent_events` calls go to the bus with a type filter
- New `_event_to_message` function replaces the inline `if event.event_type ==` checks in `_build_messages`
- `_latest_generated_result` and `_completion_content` updated for `BaseEvent` types

```python
# harness_poc/core/goal_runner.py
from __future__ import annotations

import hashlib
import json
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

import tiktoken
from pydantic import BaseModel, Field
from pydantic_ai import Agent, PromptedOutput

from harness_poc.core.events import (
    AgentStarted,
    BaseEvent,
    GoalEvaluated,
    LLMTextEmitted,
    SkillCalled,
    SkillCompleted,
)
from harness_poc.core.pydantic_runtime import build_model

if TYPE_CHECKING:
    from collections.abc import Callable

    from pydantic_ai.models import Model

    from harness_poc.app_factory import AppState
    from harness_poc.core.llm_client import Message

_encoder_cache: dict[str, tiktoken.Encoding] = {}
logger = logging.getLogger(__name__)


def _get_encoder() -> tiktoken.Encoding:
    if "enc" not in _encoder_cache:
        _encoder_cache["enc"] = tiktoken.get_encoding("cl100k_base")
    return _encoder_cache["enc"]


def count_tokens(messages: Any) -> int:  # noqa: ANN401
    r"""Count tokens in a message list using OpenAI's formula.

    Each message follows <|im_start|>{role}\n{content}<|im_end|>\n
    plus 3 tokens for the assistant priming.

    Accepts any iterable of dict-like objects (list[Message], list[dict[str, str]], etc.).
    """
    encoder = _get_encoder()
    tokens_per_message = 3
    num_tokens = 0
    for message in messages:  # type: ignore[union-attr]
        num_tokens += tokens_per_message
        for value in message.values():  # type: ignore[union-attr]
            num_tokens += len(encoder.encode(str(value)))
    num_tokens += 3  # assistant priming
    return num_tokens


def _emit_goal_progress(
    on_text: Callable[[str], None] | None,
    content: str,
) -> None:
    if on_text is not None and content:
        on_text(content)


def _event_to_message(event: BaseEvent) -> "Message | None":
    if isinstance(event, SkillCalled):
        return {
            "role": "assistant",
            "content": (
                f"[Action] Called {event.tool_name}"
                f"({json.dumps(event.arguments, sort_keys=True)})"
            ),
        }
    if isinstance(event, SkillCompleted):
        prefix = f"[Observation from {event.tool_name} — {event.status}]"
        return {"role": "user", "content": f"{prefix}\n{event.content}"}
    if isinstance(event, LLMTextEmitted):
        return {"role": "user", "content": f"[LLM text]\n{event.content}"}
    if isinstance(event, GoalEvaluated):
        return {
            "role": "user",
            "content": (
                f"[evaluate_goal: is_complete={event.is_complete}] {event.reasoning}"
            ),
        }
    return None


def _completion_content(
    *,
    goal: str,
    reasoning: str,
    final_answer: str,
    recent_events: list[BaseEvent],
) -> str:
    if final_answer:
        return final_answer

    generated_result = _latest_generated_result(recent_events)
    if generated_result and _looks_like_meta_completion(reasoning):
        return generated_result

    if reasoning:
        return reasoning
    if generated_result and _looks_like_generation_goal(goal):
        return generated_result

    return "Goal completed."


def _latest_generated_result(recent_events: list[BaseEvent]) -> str:
    for event in reversed(recent_events):
        if not isinstance(event, SkillCompleted):
            continue
        if event.status != "success":
            continue
        extracted = _extract_generated_result(event.content)
        if extracted:
            return extracted
    return ""


def _extract_generated_result(content: str) -> str:
    try:
        decoded = json.loads(content)
    except json.JSONDecodeError:
        return content
    if not isinstance(decoded, dict):
        return content

    summary = decoded.get("summary")
    if isinstance(summary, str) and summary.strip():
        return summary.strip()

    artifacts = decoded.get("artifacts")
    if isinstance(artifacts, dict):
        model_output = artifacts.get("model_output")
        if isinstance(model_output, dict):
            model_summary = model_output.get("summary")
            if isinstance(model_summary, str) and model_summary.strip():
                return model_summary.strip()

    return content


def _looks_like_meta_completion(reasoning: str) -> bool:
    normalized = reasoning.lower()
    meta_markers = (
        "skill returned",
        "delegate_task",
        "read_memory",
        "goal has been achieved",
        "goal has been completed",
        "goal is complete",
        "covers all",
        "summarizing the changes",
    )
    return any(marker in normalized for marker in meta_markers)


def _looks_like_generation_goal(goal: str) -> bool:
    normalized = goal.lower()
    return any(
        marker in normalized
        for marker in ("generate", "write", "draft", "create", "produce")
    )


@dataclass
class GoalRunResult:
    status: str  # "completed" | "budget_exhausted" | "error"
    content: str
    iterations: int
    total_tokens: int
    events: list[dict[str, Any]] = field(default_factory=list)


class GoalAction(BaseModel):
    tool_name: str = Field(
        description=(
            "Name of the next skill/tool to execute. Use evaluate_goal when "
            "the goal is complete, blocked, or needs an explicit progress check."
        ),
    )
    arguments: dict[str, Any] = Field(default_factory=dict)
    content: str = Field(
        default="",
        description=(
            "Optional plain text thought or response when no tool should be called."
        ),
    )


@dataclass
class GoalRunner:
    max_iterations: int = 50
    max_seconds: float | None = None
    max_tokens: int | None = None
    context_window: int = 20
    stuck_threshold: int = 3
    decision_model: Model | None = None

    _stuck_hashes: deque[str] = field(default_factory=lambda: deque(maxlen=3))

    def run(  # noqa: PLR0915
        self,
        goal: str,
        app_state: "AppState",
        on_text: Callable[[str], None] | None = None,
    ) -> GoalRunResult:
        """Execute the autonomous ReAct loop for the given goal."""
        logger.info(
            "Goal run started",
            extra={
                "session_id": app_state.session_id,
                "goal": goal,
                "max_iterations": self.max_iterations,
                "max_seconds": self.max_seconds,
                "max_tokens": self.max_tokens,
            },
        )
        start_time = time.monotonic()
        self._stuck_hashes.clear()
        total_tokens = 0
        events: list[dict[str, Any]] = []

        app_state.event_bus.publish(
            AgentStarted(session_id=app_state.session_id, goal=goal)
        )

        for iteration in range(1, self.max_iterations + 1):
            # --- Budget: time ---
            if self.max_seconds is not None:
                elapsed = time.monotonic() - start_time
                if elapsed >= self.max_seconds:
                    logger.warning(
                        "Goal run exhausted time budget",
                        extra={
                            "session_id": app_state.session_id,
                            "goal": goal,
                            "iterations": iteration - 1,
                            "elapsed": elapsed,
                        },
                    )
                    return GoalRunResult(
                        status="budget_exhausted",
                        content=(
                            f"Time budget ({self.max_seconds}s) exhausted "
                            f"after {iteration - 1} iterations."
                        ),
                        iterations=iteration - 1,
                        total_tokens=total_tokens,
                        events=events,
                    )

            # --- Build context window ---
            recent_events = app_state.event_bus.get_recent_events(
                app_state.session_id,
                limit=self.context_window,
                event_types=[SkillCalled, SkillCompleted, GoalEvaluated, LLMTextEmitted],
            )

            # --- Build messages for LLM ---
            messages = self._build_messages(goal, recent_events)

            # --- Budget: tokens ---
            if self.max_tokens is not None:
                token_count = count_tokens(messages)
                if total_tokens + token_count >= self.max_tokens:
                    logger.warning(
                        "Goal run exhausted token budget",
                        extra={
                            "session_id": app_state.session_id,
                            "goal": goal,
                            "iterations": iteration - 1,
                            "total_tokens": total_tokens,
                            "next_context_tokens": token_count,
                        },
                    )
                    return GoalRunResult(
                        status="budget_exhausted",
                        content=(
                            f"Token budget ({self.max_tokens}) exhausted "
                            f"after {iteration - 1} iterations."
                        ),
                        iterations=iteration - 1,
                        total_tokens=total_tokens,
                        events=events,
                    )

            # --- PydanticAI structured decision ---
            action, response_tokens = self._decide_next_action(
                goal=goal,
                app_state=app_state,
                recent_events=recent_events,
            )
            if self.max_tokens is not None:
                total_tokens += token_count + response_tokens

            # --- _llm_text path ---
            if action.tool_name == "_llm_text":
                app_state.event_bus.publish(
                    LLMTextEmitted(
                        session_id=app_state.session_id,
                        content=action.content,
                    )
                )
                events.append(
                    {
                        "type": "tool_observation",
                        "tool": "_llm_text",
                        "content": action.content[:200],
                    }
                )
                continue

            tool_name = action.tool_name
            arguments = action.arguments
            _emit_goal_progress(
                on_text,
                f"\n[goal] iteration {iteration}: {tool_name}\n",
            )
            logger.info(
                "Goal action selected",
                extra={
                    "session_id": app_state.session_id,
                    "goal": goal,
                    "iteration": iteration,
                    "tool_name": tool_name,
                    "arguments": arguments,
                },
            )

            # --- Stuck detection ---
            action_hash = self._hash_action(tool_name, arguments)
            if self._is_stuck(action_hash):
                error_msg = (
                    "STUCK DETECTION: You have attempted the same action "
                    f"({tool_name}) with identical arguments "
                    f"{self.stuck_threshold}+ times. The action was blocked. "
                    "Step back and try a different approach."
                )
                logger.warning(
                    "Goal action blocked by stuck detection",
                    extra={
                        "session_id": app_state.session_id,
                        "goal": goal,
                        "iteration": iteration,
                        "tool_name": tool_name,
                    },
                )
                app_state.event_bus.publish(
                    SkillCompleted(
                        session_id=app_state.session_id,
                        tool_name=tool_name,
                        status="blocked",
                        content=error_msg,
                    )
                )
                events.append(
                    {
                        "type": "tool_observation",
                        "tool": tool_name,
                        "status": "blocked",
                        "content": "Stuck detection triggered.",
                    }
                )
                continue

            self._stuck_hashes.append(action_hash)

            # --- Intercept evaluate_goal ---
            if tool_name == "evaluate_goal":
                is_complete: bool = arguments.get("is_complete", False)
                reasoning: str = arguments.get("reasoning", "")
                final_answer = str(arguments.get("final_answer") or "").strip()
                if reasoning:
                    _emit_goal_progress(
                        on_text, f"[goal] reasoning: {reasoning}\n"
                    )

                app_state.event_bus.publish(
                    GoalEvaluated(
                        session_id=app_state.session_id,
                        is_complete=is_complete,
                        reasoning=reasoning,
                        final_answer=final_answer,
                    )
                )

                if is_complete:
                    content = _completion_content(
                        goal=goal,
                        reasoning=reasoning,
                        final_answer=final_answer,
                        recent_events=recent_events,
                    )
                    logger.info(
                        "Goal run completed",
                        extra={
                            "session_id": app_state.session_id,
                            "goal": goal,
                            "iteration": iteration,
                            "total_tokens": total_tokens,
                        },
                    )
                    return GoalRunResult(
                        status="completed",
                        content=content,
                        iterations=iteration,
                        total_tokens=total_tokens,
                        events=events,
                    )

                events.append(
                    {
                        "type": "tool_observation",
                        "tool": "evaluate_goal",
                        "content": f"Not complete: {reasoning[:200]}",
                    }
                )
                continue

            # --- Execute normal skill ---
            app_state.event_bus.publish(
                SkillCalled(
                    session_id=app_state.session_id,
                    tool_name=tool_name,
                    arguments=arguments,
                )
            )
            events.append(
                {
                    "type": "llm_action",
                    "tool": tool_name,
                    "arguments": arguments,
                }
            )
            try:
                result = app_state.skill_runner.execute_skill(
                    tool_name=tool_name,
                    arguments=arguments,
                    session_id=app_state.session_id,
                    on_text=on_text,
                )
                app_state.event_bus.publish(
                    SkillCompleted(
                        session_id=app_state.session_id,
                        tool_name=tool_name,
                        status=result.status,
                        content=result.content,
                        artifacts=result.artifacts,
                    )
                )
                events.append(
                    {
                        "type": "tool_observation",
                        "tool": tool_name,
                        "status": result.status,
                        "content": result.content[:200],
                    }
                )
            except (OSError, RuntimeError, TypeError, ValueError) as exc:
                error_msg = f"Skill execution failed: {exc}"
                logger.exception(
                    "Goal skill execution failed",
                    extra={
                        "session_id": app_state.session_id,
                        "goal": goal,
                        "iteration": iteration,
                        "tool_name": tool_name,
                    },
                )
                app_state.event_bus.publish(
                    SkillCompleted(
                        session_id=app_state.session_id,
                        tool_name=tool_name,
                        status="error",
                        content=error_msg,
                    )
                )
                events.append(
                    {
                        "type": "tool_observation",
                        "tool": tool_name,
                        "status": "error",
                        "content": error_msg,
                    }
                )

        # --- Budget exhausted (iterations) ---
        logger.warning(
            "Goal run exhausted iteration budget",
            extra={
                "session_id": app_state.session_id,
                "goal": goal,
                "iterations": self.max_iterations,
                "total_tokens": total_tokens,
            },
        )
        return GoalRunResult(
            status="budget_exhausted",
            content=(
                f"Iteration budget ({self.max_iterations}) exhausted. Goal may be incomplete."
            ),
            iterations=self.max_iterations,
            total_tokens=total_tokens,
            events=events,
        )

    def _build_messages(
        self,
        goal: str,
        recent_events: list[BaseEvent],
    ) -> list["Message"]:
        """Build message list: system prompt + formatted event history + continue prompt."""
        system_prompt = self._goal_system_prompt(goal)
        messages: list[Message] = [
            {"role": "system", "content": system_prompt},
        ]

        for event in recent_events:
            msg = _event_to_message(event)
            if msg is not None:
                messages.append(msg)

        messages.append(
            {
                "role": "user",
                "content": (
                    "Continue working toward the goal. Take the next concrete action. "
                    "If the goal is fully achieved, call evaluate_goal with "
                    "is_complete=true and explain what was accomplished. "
                    "If you are stuck or cannot proceed, call evaluate_goal with "
                    "is_complete=false and explain what is blocking you."
                ),
            }
        )
        return messages

    def _decide_next_action(
        self,
        *,
        goal: str,
        app_state: "AppState",
        recent_events: list[BaseEvent],
    ) -> tuple[GoalAction, int]:
        model = (
            self.decision_model
            or app_state.goal_decision_model
            or build_model()
        )
        logger.debug(
            "Requesting goal decision",
            extra={
                "session_id": app_state.session_id,
                "recent_event_count": len(recent_events),
                "tool_count": len(app_state.tools),
            },
        )
        agent = Agent(
            model,
            output_type=PromptedOutput(
                GoalAction,
                name="goal_action",
                description=(
                    "Return the next harness skill to execute as JSON. "
                    "Do not call the skill directly."
                ),
            ),
            system_prompt=self._goal_system_prompt(goal),
            output_retries=2,
        )
        result = agent.run_sync(
            self._build_decision_prompt(recent_events, app_state.tools),
        )
        usage = result.usage
        response_tokens = int(usage.output_tokens or 0)
        action = cast("GoalAction", result.output)
        logger.debug(
            "Goal decision received",
            extra={
                "session_id": app_state.session_id,
                "tool_name": action.tool_name,
                "response_tokens": response_tokens,
            },
        )
        return action, response_tokens

    @staticmethod
    def _build_decision_prompt(
        recent_events: list[BaseEvent],
        tools: list[dict[str, Any]],
    ) -> str:
        parts = [
            "Choose the next concrete action as structured output.",
            "",
            "## Available Tools",
            json.dumps(tools, indent=2, sort_keys=True),
            "",
            "## Recent Events",
        ]

        if recent_events:
            parts.extend(
                f"- {event.event_type}: {event.model_dump_json(sort_keys=True)}"
                for event in recent_events
            )
        else:
            parts.append("No prior events.")

        parts.extend(
            [
                "",
                "## Required Response",
                "Return a structured object with:",
                "- tool_name: the skill/tool to call next.",
                "- arguments: the JSON arguments for that tool.",
                "- content: optional text only when tool_name is _llm_text.",
                "",
                "Do not call any of these tools directly. Return the selected tool "
                "name and arguments as JSON matching the requested structured output.",
                "",
                "Use evaluate_goal with is_complete=true when the goal is fully achieved. "
                "For generation goals, include the generated artifact verbatim in "
                "arguments.final_answer. The user should not need to inspect memory or "
                "logs to see the generated result. "
                "Use evaluate_goal with is_complete=false when progress is incomplete or blocked.",
            ],
        )
        return "\n".join(parts)

    @staticmethod
    def _goal_system_prompt(goal: str) -> str:
        return (
            "You are an autonomous agent operating in a ReAct (Reason + Act) loop. "
            "Your sole objective is to achieve the following goal.\n\n"
            f"## Goal\n{goal}\n\n"
            "## Instructions\n"
            "- Work step by step. Call tools to take actions.\n"
            "- After each tool result, decide on your next action.\n"
            "- When the goal is fully achieved, call `evaluate_goal` with "
            "`is_complete: true` and explain what was accomplished. If the goal "
            "asked you to generate, draft, write, or produce text, include that "
            "generated text verbatim in `final_answer`; do not only describe where "
            "it was produced.\n"
            "- If you are stuck or cannot proceed, call `evaluate_goal` with "
            "`is_complete: false` and explain what is blocking you.\n"
            "- Do not repeat the same action with identical arguments — the system "
            "will block repeated patterns.\n"
            "- Be concise. Focus on actions, not conversation.\n"
        )

    @staticmethod
    def _hash_action(tool_name: str, arguments: dict[str, Any]) -> str:
        canonical = json.dumps(
            {"tool": tool_name, "args": arguments}, sort_keys=True
        )
        return hashlib.sha256(canonical.encode()).hexdigest()

    def _is_stuck(self, action_hash: str) -> bool:
        if len(self._stuck_hashes) < self.stuck_threshold:
            return False
        return all(h == action_hash for h in self._stuck_hashes)
```

- [ ] **Step 2: Update `tests/test_goal_runner.py`**

Replace the four database event tests and update the three tests that query events. The tests that DON'T touch events (`test_completes_on_evaluate_goal_true`, `test_continues_on_evaluate_goal_false`, `test_iteration_budget_exhausted`, etc.) are unchanged.

Remove these four tests entirely (they are superseded by `test_event_store.py`):
- `test_record_and_retrieve_events`
- `test_get_recent_events_respects_limit`
- `test_get_recent_events_returns_chronological`
- `test_get_recent_events_filters_non_goal_events`

Replace these three tests:

```python
# Replace test_text_response_without_tool_call
def test_text_response_without_tool_call() -> None:
    """Text responses should be recorded as LLMTextEmitted and loop continues."""
    from harness_poc.core.events import LLMTextEmitted

    mock = _mock_response_factory(
        [
            LLMResponse(kind="text", content="Let me think about this..."),
            _evaluate_goal_response(True, "I thought about it."),
        ]
    )
    state = _make_app_state(mock)
    runner = GoalRunner(max_iterations=10)

    result = runner.run("Test goal", state)
    assert result.status == "completed"
    assert result.iterations == 2
    events = state.event_bus.get_recent_events(state.session_id)
    text_events = [e for e in events if isinstance(e, LLMTextEmitted)]
    assert len(text_events) == 1


# Replace test_stuck_detection_blocks_fourth_identical_action
def test_stuck_detection_blocks_fourth_identical_action() -> None:
    """Identical (tool, args) 4 times in a row should trigger stuck detection."""
    from harness_poc.core.events import SkillCompleted

    mock = _mock_response_factory([_tool_call_response("read_memory", {"memory_key": "x"})])
    state = _make_app_state(mock)
    runner = GoalRunner(max_iterations=10, stuck_threshold=3)

    result = runner.run("Test goal", state)
    assert result.status == "budget_exhausted"
    events = state.event_bus.get_recent_events(state.session_id)
    blocked = [e for e in events if isinstance(e, SkillCompleted) and e.status == "blocked"]
    assert len(blocked) >= 1


# Replace test_skill_execution_error_handled
def test_skill_execution_error_handled() -> None:
    """Skill errors should be recorded as SkillCompleted(error) and loop continues."""
    from harness_poc.core.events import SkillCompleted

    mock = _mock_response_factory(
        [
            _tool_call_response("nonexistent_skill", {}),
            _evaluate_goal_response(True, "Handled error."),
        ]
    )
    state = _make_app_state(mock)
    runner = GoalRunner(max_iterations=10)

    result = runner.run("Test goal", state)
    assert result.status == "completed"
    events = state.event_bus.get_recent_events(state.session_id)
    errors = [e for e in events if isinstance(e, SkillCompleted) and e.status == "error"]
    assert len(errors) >= 1


# Replace test_context_window_builds_from_events
def test_context_window_builds_from_events() -> None:
    """Verify that the context window is populated from bus events."""
    from harness_poc.core.events import AgentStarted

    mock = _mock_response_factory(
        [
            _tool_call_response("read_memory", {"memory_key": "test"}),
            _evaluate_goal_response(True, "Done."),
        ]
    )
    state = _make_app_state(mock)
    runner = GoalRunner(max_iterations=10, context_window=5)

    result = runner.run("Test", state)
    assert result.status == "completed"
    all_events = state.event_bus.get_recent_events(state.session_id)
    # AgentStarted + SkillCalled + SkillCompleted + GoalEvaluated = 4
    assert len(all_events) >= 4
    assert any(isinstance(e, AgentStarted) for e in all_events)
```

- [ ] **Step 3: Run full test suite**

```bash
uv run pytest -v
```
Expected: all tests PASS. The four removed DB-event tests no longer exist; all GoalRunner behavior tests still pass.

- [ ] **Step 4: Lint and type-check**

```bash
uv run ruff check harness_poc/core/goal_runner.py tests/test_goal_runner.py
uv run ty check
```

- [ ] **Step 5: Commit**

```bash
git add harness_poc/core/goal_runner.py tests/test_goal_runner.py
git commit -m "feat: refactor GoalRunner to publish typed events via EventBus"
```

---

## Task 6: Remove dead database event methods

**Files:**
- Modify: `harness_poc/core/database.py`

The methods `record_llm_action`, `record_tool_observation`, and `get_recent_events` on `BlackboardDatabase` are no longer called anywhere — `GoalRunner` uses the bus. Remove them.

Note: `_insert_state_event` stays — it is still used transactionally by `append_session_state`, `create_state_proposal`, `approve_state_proposal`, and `reject_state_proposal`.

- [ ] **Step 1: Confirm no remaining callers**

```bash
grep -rn "record_llm_action\|record_tool_observation\|\.get_recent_events" \
  harness_poc/ tests/ --include="*.py"
```
Expected: zero matches (only the definitions in `database.py` itself, which we're about to remove).

- [ ] **Step 2: Remove the three methods from `database.py`**

Delete lines containing the `record_llm_action`, `record_tool_observation`, and `get_recent_events` method bodies from `harness_poc/core/database.py`. The methods to remove are:

```python
# DELETE this method:
def record_llm_action(
    self,
    session_id: str,
    tool_name: str,
    arguments: dict[str, Any],
) -> None:
    now = self._utc_now()
    with self._connect() as connection:
        self._insert_state_event(
            connection=connection,
            event=StateEvent(
                scope="session",
                scope_id=session_id,
                event_type="llm_action",
                payload={
                    "tool_name": tool_name,
                    "arguments": arguments,
                },
                created_at=now,
            ),
        )

# DELETE this method:
def record_tool_observation(
    self,
    session_id: str,
    tool_name: str,
    status: str,
    content: str,
) -> None:
    now = self._utc_now()
    with self._connect() as connection:
        self._insert_state_event(
            connection=connection,
            event=StateEvent(
                scope="session",
                scope_id=session_id,
                event_type="tool_observation",
                payload={
                    "tool_name": tool_name,
                    "status": status,
                    "content": content,
                },
                created_at=now,
            ),
        )

# DELETE this method:
def get_recent_events(
    self, session_id: str, limit: int = 20
) -> list[StateEvent]:
    with self._connect() as connection:
        cursor = connection.execute(
            """
            SELECT scope, scope_id, event_type, payload, created_at
            FROM state_events
            WHERE scope = 'session'
              AND scope_id = ?
              AND event_type IN ('llm_action', 'tool_observation')
            ORDER BY id DESC
            LIMIT ?
            """,
            (session_id, limit),
        )
        rows = cursor.fetchall()

    events = [
        StateEvent(
            scope=str(row["scope"]),
            scope_id=str(row["scope_id"]),
            event_type=str(row["event_type"]),
            payload=json.loads(str(row["payload"])),
            created_at=str(row["created_at"]),
        )
        for row in rows
    ]
    events.reverse()
    return events
```

- [ ] **Step 3: Run full test suite**

```bash
uv run pytest -v
```
Expected: all tests PASS.

- [ ] **Step 4: Lint and type-check**

```bash
uv run ruff check harness_poc/core/database.py
uv run ty check
```

- [ ] **Step 5: Commit**

```bash
git add harness_poc/core/database.py
git commit -m "refactor: remove dead DB event methods superseded by EventBus"
```

---

## Task 7: Integration test

**Files:**
- Modify: `tests/test_goal_runner.py` (add one test)

- [ ] **Step 1: Add end-to-end integration test**

Append to `tests/test_goal_runner.py`:

```python
def test_goal_runner_publishes_correct_event_sequence() -> None:
    """End-to-end: bus contains AgentStarted → SkillCalled → SkillCompleted → GoalEvaluated."""
    from harness_poc.core.events import (
        AgentStarted,
        GoalEvaluated,
        SkillCalled,
        SkillCompleted,
    )

    mock = _mock_response_factory(
        [
            _tool_call_response("read_memory", {"memory_key": "test"}),
            _evaluate_goal_response(True, "All done."),
        ]
    )
    state = _make_app_state(mock)
    runner = GoalRunner(max_iterations=10)

    result = runner.run("Test event sequence", state)
    assert result.status == "completed"

    all_events = state.event_bus.get_recent_events(state.session_id)
    types = [type(e) for e in all_events]

    assert AgentStarted in types
    assert SkillCalled in types
    assert SkillCompleted in types
    assert GoalEvaluated in types

    # AgentStarted must be first
    assert isinstance(all_events[0], AgentStarted)
    # GoalEvaluated must be last
    assert isinstance(all_events[-1], GoalEvaluated)
    assert all_events[-1].is_complete is True
```

- [ ] **Step 2: Run the integration test**

```bash
uv run pytest tests/test_goal_runner.py::test_goal_runner_publishes_correct_event_sequence -v
```
Expected: PASS.

- [ ] **Step 3: Run full test suite one final time**

```bash
uv run pytest -v
```
Expected: all tests PASS, no regressions.

- [ ] **Step 4: Lint and type-check**

```bash
uv run ruff check .
uv run ty check
```

- [ ] **Step 5: Commit**

```bash
git add tests/test_goal_runner.py
git commit -m "test: add end-to-end event sequence integration test"
```
