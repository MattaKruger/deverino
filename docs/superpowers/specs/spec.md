Here is the technical implementation specification. You can provide this document directly to Codex, Cursor, or your chosen AI assistant to dictate the exact file structures, class signatures, and behavioral constraints required for the migration.

---

# Event-Sourced Agent Harness: Implementation Specification

## 1. Architectural Invariants

* **Zero Mutable State:** Processors must never hold state in memory between event loops. All decisions are based on the derived state from the `EventBus`.
* **Asynchronous Concurrency:** All processors must run as independent `asyncio` tasks. Blocking operations (I/O, database writes) must yield to the event loop.
* **Type Safety & Linting:** Strict adherence to Pydantic validation for all event payloads. Code must pass `ruff check` and `ruff format` without warnings.
* **Dependency Management:** All new dependencies must be managed via `uv`.

## 2. Dependency Updates

Execute the following to update the project environment:

```bash
uv add aiosqlite polars pydantic

```

## 3. Module Specifications

### A. Core Database & Schemas

**File:** `harness_poc/core/database.py`
Migrate the existing synchronous SQLite connection to `aiosqlite`.

* **Behavioral Rules:**
* On initialization, the database must execute `PRAGMA journal_mode=WAL;` to allow concurrent reads during processor execution.
* Deprecate/remove `project_state` and `session_state` tables.


* **Schema Additions:**
```sql
CREATE TABLE IF NOT EXISTS session_snapshots (
    session_id TEXT PRIMARY KEY,
    last_offset INTEGER NOT NULL,
    state_payload TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

```



### B. Event Definitions

**File:** `harness_poc/core/events.py`
Define the strict Pydantic models that act as the schema for the SQLite JSON payloads.

* **Classes to Implement:**
* `BaseEvent(BaseModel)`: Must include `id` (offset, optional on creation), `session_id`, `timestamp`, and `type_name`.
* `AgentInputAdded(BaseEvent)`: Payload includes `user_content: str`.
* `SkillRequested(BaseEvent)`: Payload includes `skill_name: str`, `arguments: dict`.
* `SkillCompleted(BaseEvent)`: Payload includes `skill_name: str`, `status: Literal["success", "failed"]`, `result: str`.
* `LLMActionEmitted(BaseEvent)`: Payload includes `tokens_used: int`, `model: str`.
* `StreamPaused(BaseEvent)`: Payload includes `reason: str` (e.g., "budget_exhausted", "consecutive_failures").



### C. State Derivation (Reducer)

**File:** `harness_poc/core/reducers.py` (New File)
Implement the synchronous logic to derive state, wrapped in an async database fetcher.

* **Signatures:**
```python
import polars as pl
import aiosqlite

async def derive_session_state(db_path: str, session_id: str) -> dict:
    """
    1. Fetches the latest snapshot from `session_snapshots`.
    2. Fetches all events from `state_events` where offset > snapshot.last_offset.
    3. Parses events into a Polars DataFrame for fast aggregation.
    4. Calculates total_tokens, consecutive_skill_failures, and recent_message_history.
    5. Updates and returns the new state dictionary.
    """
    pass

```



### D. The Asynchronous Event Bus

**File:** `harness_poc/core/event_bus.py`
Refactor the bus to act as both the durable SQLite writer and the high-speed in-memory queue for local workers.

* **Signatures:**
```python
import asyncio
from typing import AsyncGenerator

class EventBus:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._queue: asyncio.Queue = asyncio.Queue()

    async def publish(self, event: BaseEvent) -> None:
        """
        1. Write the event to the SQLite `state_events` table (durability).
        2. Push the committed event to `self._queue` (speed).
        """
        pass

    async def subscribe(self, session_id: str) -> AsyncGenerator[BaseEvent, None]:
        """
        Yields events from the queue that match the session_id.
        """
        pass

```



### E. Circuit Breaker Processor

**File:** `harness_poc/core/processors/circuit_breaker.py` (New File)
A standalone safety worker.

* **Signatures:**
```python
async def run_circuit_breaker(bus: EventBus, session_id: str, max_retries: int, max_tokens: int) -> None:
    """
    1. Subscribes to the bus.
    2. Tracks failures and tokens internally.
    3. If thresholds are breached, calls bus.publish(StreamPaused(...)).
    """
    pass

```



### F. LLM and Skill Workers

**Files:** `harness_poc/core/processors/llm_worker.py`, `harness_poc/core/processors/skill_worker.py` (New Files)
Isolate external execution.

* **LLM Worker Behavior:**
* Subscribes to `AgentInputAdded` and `SkillCompleted`.
* When triggered, calls `derive_session_state`.
* Checks if state contains a `StreamPaused` event in history. If so, `break` the loop.
* Executes `pydantic_ai.Agent.run()` restricted to a single turn.
* Publishes `SkillRequested` or `LLMActionEmitted`.


* **Skill Worker Behavior:**
* Subscribes to `SkillRequested`.
* Executes the requested tool logic.
* Publishes `SkillCompleted`.



### G. Entry Point Orchestration

**File:** `harness_poc/main.py`
Tear down the synchronous loop and wire up the `asyncio` ecosystem.

* **Signatures:**
```python
import asyncio

async def main(session_id: str):
    bus = EventBus("harness.db")

    # Start all processors concurrently
    await asyncio.gather(
        run_circuit_breaker(bus, session_id, max_retries=3, max_tokens=10000),
        run_llm_worker(bus, session_id),
        run_skill_worker(bus, session_id)
    )

```
