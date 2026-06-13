# Context Map: Implementation Spec

**Date:** 2026-05-20
**Status:** ready-for-implementation
**Design ref:** `docs/superpowers/specs/2026-05-20-event-sourced-context-map-design.md`
**Target:** Codex / autonomous implementation agent

---

## Overview

Implement the event-sourced context map system in three phases. Each phase is independently
deployable. Phase 1 (Foundation) is the minimum viable slice: schema, events, and a manually
invoked materializer skill. Phases 2 and 3 wire it into the running harness.

This spec is prescriptive. Follow the file paths, class names, and method signatures exactly.
Where behaviour is underspecified, prefer the simplest correct implementation.

---

## Repo conventions (read before writing any code)

- Python 3.12. `from __future__ import annotations` at top of every file.
- Ruff: `line-length = 100`, double quotes, `S101` ignored under `tests/`.
- No comments unless the WHY is non-obvious.
- `SkillResult(status, content, artifacts)` — the only return type for skill `execute()`.
- LLM calls from skills: `chat_text(messages, model=build_model(ctx.config.llm))` from
  `harness_poc.core.pydantic_runtime`.
- Database access in skills: `ctx.database` (typed as `BlackboardDatabase | BlackboardAccessProxy`).
- All timestamps: `datetime.now(tz=UTC).isoformat(timespec="seconds")`.

---

## Phase 1 — Foundation

**Goal:** Schema exists, events can be appended, materializer can be run manually.
No changes to the agent loop yet.

### 1.1 Add `project_id` to config

**File: `harness.yaml`** — add under a new top-level `project:` section:

```yaml
project:
  id: deverino
```

**File: `harness_poc/core/config.py`**

Add `project_id: str` to the `HarnessConfig` dataclass (after `retrieval`):

```python
project_id: str = field(default="default")
```

In `HarnessConfig.load()`, after the `retrieval = ...` block, add:

```python
import hashlib  # at top of file

project_raw = _mapping(raw.get("project"), "project")
project_id = str(project_raw.get("id") or "")
if not project_id:
    project_id = hashlib.md5(str(project_root).encode()).hexdigest()[:8]
```

Then pass `project_id=project_id` to the `cls(...)` constructor call at the bottom of `load()`.

---

### 1.2 Create event models

**New file: `harness_poc/core/context_map_events.py`**

```python
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ContextMapEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = Field(default_factory=lambda: datetime.now(tz=UTC).isoformat(timespec="seconds"))
    session_id: str
    corpus_key: str
    event_type: str


class CorpusIngested(ContextMapEvent):
    event_type: Literal["corpus_ingested"] = "corpus_ingested"
    corpus_name: str
    document_count: int
    total_tokens: int
    schema_hint: str | None = None


class DocumentRetrieved(ContextMapEvent):
    event_type: Literal["document_retrieved"] = "document_retrieved"
    query: str
    retrieved_doc_ids: list[str]
    retrieved_doc_titles: list[str]
    retrieval_strategy: str


class EntityReferenced(ContextMapEvent):
    event_type: Literal["entity_referenced"] = "entity_referenced"
    entity_name: str
    entity_type: str
    context: str


class SchemaDiscovered(ContextMapEvent):
    event_type: Literal["schema_discovered"] = "schema_discovered"
    schema_description: str
    example: str


class SearchFailed(ContextMapEvent):
    event_type: Literal["search_failed"] = "search_failed"
    attempted_query: str
    strategy: str
    error: str


class FactDisputed(ContextMapEvent):
    event_type: Literal["fact_disputed"] = "fact_disputed"
    previous_claim: str
    corrected_claim: str
    source_doc_id: str


class ContextualInsightDiscovered(ContextMapEvent):
    event_type: Literal["contextual_insight_discovered"] = "contextual_insight_discovered"
    insight: str
    supporting_events: list[str]
    map_section: str


class MapEntryPromoted(ContextMapEvent):
    event_type: Literal["map_entry_promoted"] = "map_entry_promoted"
    entry_key: str
    from_section: str
    to_section: str


class MapEntryEvicted(ContextMapEvent):
    event_type: Literal["map_entry_evicted"] = "map_entry_evicted"
    entry_key: str
    section: str
    reason: str


EVENT_REGISTRY: dict[str, type[ContextMapEvent]] = {
    "corpus_ingested": CorpusIngested,
    "document_retrieved": DocumentRetrieved,
    "entity_referenced": EntityReferenced,
    "schema_discovered": SchemaDiscovered,
    "search_failed": SearchFailed,
    "fact_disputed": FactDisputed,
    "contextual_insight_discovered": ContextualInsightDiscovered,
    "map_entry_promoted": MapEntryPromoted,
    "map_entry_evicted": MapEntryEvicted,
}


def deserialize_event(data: dict[str, Any]) -> ContextMapEvent:
    event_type = str(data.get("event_type", ""))
    cls = _REGISTRY.get(event_type, ContextMapEvent)
    return cls.model_validate(data)
```

---

### 1.3 Add SQLModel tables

**File: `harness_poc/core/models.py`** — append after `DbDocumentChunk`:

```python
class DbContextMapEvent(SQLModel, table=True):
    __tablename__ = "context_map_events"  # type: ignore[assignment]
    __table_args__ = (
        Index(
            "idx_context_map_events_corpus_unprocessed",
            "corpus_key",
            "processed",
            "timestamp",
        ),
    )

    event_id: str = Field(primary_key=True)
    corpus_key: str
    session_id: str
    event_type: str
    payload: str = Field(sa_column=Column(Text, nullable=False))  # JSON-encoded event
    timestamp: str
    processed: int = Field(default=0)


class DbContextMap(SQLModel, table=True):
    __tablename__ = "context_map"  # type: ignore[assignment]

    corpus_key: str = Field(primary_key=True)
    map_json: str = Field(sa_column=Column(Text, nullable=False))  # JSON
    token_count: int
    version: int = Field(default=1)
    last_updated: str
```

Both use `Column(Text, ...)` — no JSONB variant needed (payload is always serialized to a string).

---

### 1.4 Add database methods

**File: `harness_poc/core/database.py`**

Add the following imports at the top (under existing imports):

```python
from harness_poc.core.context_map_events import ContextMapEvent
from harness_poc.core.models import DbContextMap, DbContextMapEvent
```

Add these methods to `BlackboardDatabase`:

```python
def append_context_map_event(self, event: ContextMapEvent) -> None:
    with Session(self._engine) as session:
        session.add(
            DbContextMapEvent(
                event_id=event.event_id,
                corpus_key=event.corpus_key,
                session_id=event.session_id,
                event_type=event.event_type,
                payload=event.model_dump_json(),
                timestamp=event.timestamp,
                processed=0,
            )
        )
        session.commit()

def get_pending_context_map_events(
    self, corpus_key: str, limit: int = 50
) -> list[DbContextMapEvent]:
    with Session(self._engine) as session:
        return list(
            session.exec(
                select(DbContextMapEvent)
                .where(DbContextMapEvent.corpus_key == corpus_key)
                .where(DbContextMapEvent.processed == 0)
                .order_by(DbContextMapEvent.timestamp)
                .limit(limit)
            ).all()
        )

def get_pending_corpus_keys(self) -> list[str]:
    with Session(self._engine) as session:
        rows = session.exec(
            select(DbContextMapEvent.corpus_key)
            .where(DbContextMapEvent.processed == 0)
            .distinct()
        ).all()
    return list(rows)

def get_context_map(self, corpus_key: str) -> dict[str, Any] | None:
    with Session(self._engine) as session:
        row = session.get(DbContextMap, corpus_key)
    if row is None:
        return None
    try:
        return json.loads(row.map_json)
    except json.JSONDecodeError:
        return None

def write_map_and_mark_processed(
    self,
    corpus_key: str,
    map_json: dict[str, Any],
    token_count: int,
    event_ids: list[str],
) -> None:
    """Write context map and mark events processed in a single transaction."""
    now = self._utc_now()
    serialized = json.dumps(map_json, sort_keys=True)
    with Session(self._engine) as session:
        row = session.get(DbContextMap, corpus_key)
        if row is None:
            session.add(
                DbContextMap(
                    corpus_key=corpus_key,
                    map_json=serialized,
                    token_count=token_count,
                    version=1,
                    last_updated=now,
                )
            )
        else:
            row.map_json = serialized
            row.token_count = token_count
            row.version += 1
            row.last_updated = now
            session.add(row)
        for event_id in event_ids:
            event_row = session.get(DbContextMapEvent, event_id)
            if event_row is not None:
                event_row.processed = 1
                session.add(event_row)
        session.commit()
```

> **Atomicity note:** SQLModel's `Session.commit()` is a single database transaction. For
> PostgreSQL (the production backend) this is fully atomic. For SQLite (tests), the default
> WAL mode makes this safe for single-writer scenarios. If concurrent `MaterializerRunner`
> instances become a concern in Phase 3, add `BEGIN EXCLUSIVE` via a raw connection —
> document that as a follow-up in Phase 3.

---

### 1.5 Create `append_event` system skill

**New directory: `harness_poc/system_skills/append_event/`**

**`harness_poc/system_skills/append_event/SKILL.md`**:

```markdown
---
name: append_event
type: tool
description: Append a typed event to the context map event store for later materialization.
version: "1.0"
auto_invokable: false
parameters:
  type: object
  properties:
    event_type:
      type: string
      description: >
        One of: corpus_ingested, document_retrieved, entity_referenced, schema_discovered,
        search_failed, fact_disputed.
    corpus_key:
      type: string
      description: "{project_id}:{corpus_name}", e.g. "deverino:codebase".
    payload:
      type: object
      description: Fields required by the event_type (see context_map_events.py).
  required:
    - event_type
    - corpus_key
    - payload
entrypoint:
  module: skill
  function: execute
permissions:
  blackboard: read_write
  workspace: none
---

# Skill: append_event

Inserts a structured event into `context_map_events`. The MaterializerRunner
picks it up asynchronously and updates the context map.
```

**`harness_poc/system_skills/append_event/skill.py`**:

```python
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from harness_poc.core.context_map_events import EVENT_REGISTRY, ContextMapEvent
from harness_poc.core.skill_context import SkillResult

if TYPE_CHECKING:
    from harness_poc.core.skill_context import SkillContext


def execute(ctx: SkillContext, arguments: dict[str, Any]) -> SkillResult:
    event_type = str(arguments.get("event_type") or "").strip()
    corpus_key = str(arguments.get("corpus_key") or "").strip()
    payload = arguments.get("payload")

    if not event_type:
        return SkillResult(status="failed", content="Missing required argument: event_type", artifacts={})
    if not corpus_key:
        return SkillResult(status="failed", content="Missing required argument: corpus_key", artifacts={})
    if not isinstance(payload, dict):
        return SkillResult(status="failed", content="payload must be a JSON object", artifacts={})

    cls = EVENT_REGISTRY.get(event_type)
    if cls is None:
        return SkillResult(
            status="failed",
            content=f"Unknown event_type: {event_type!r}. Valid types: {sorted(EVENT_REGISTRY)}",
            artifacts={},
        )

    try:
        event = cls.model_validate(
            {
                **payload,
                "event_type": event_type,
                "corpus_key": corpus_key,
                "session_id": ctx.session_id,
            }
        )
    except Exception as exc:  # noqa: BLE001
        return SkillResult(status="failed", content=f"Invalid payload: {exc}", artifacts={})

    ctx.database.append_context_map_event(event)  # type: ignore[union-attr]

    return SkillResult(
        status="success",
        content=f"Event {event.event_id} ({event_type}) appended to {corpus_key}.",
        artifacts={"event_id": event.event_id, "corpus_key": corpus_key},
    )
```

> Note: `ctx.database` may be a `BlackboardAccessProxy`. The `append_context_map_event` method
> must be exposed through the proxy. Check `harness_poc/core/blackboard_proxy.py` and add a
> delegation if the method is missing.

---

### 1.6 Create `context-map-materializer` project skill

**New directory: `skills/context-map-materializer/`**

**`skills/context-map-materializer/SKILL.md`**:

```markdown
---
name: context-map-materializer
type: tool
description: >
  Run the Distiller → Cartographer → Evictor pipeline for a corpus_key.
  Fetches unprocessed events, calls two LLM passes, and atomically updates the context map.
version: "1.0"
auto_invokable: false
parameters:
  type: object
  properties:
    corpus_key:
      type: string
      description: The corpus to materialize, e.g. "deverino:codebase".
    max_event_tokens:
      type: integer
      description: Approximate token budget for event input to the Distiller.
      default: 8000
    token_budget:
      type: integer
      description: Maximum token budget for the context map.
      default: 1024
  required:
    - corpus_key
entrypoint:
  module: skill
  function: execute
permissions:
  blackboard: read_write
  workspace: none
---

# Skill: context-map-materializer

Runs the full Distiller → Cartographer → Evictor pipeline for one corpus.
Safe to run multiple times; idempotent (already-processed events are skipped).
```

**`skills/context-map-materializer/skill.py`**:

```python
from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from harness_poc.core.pydantic_runtime import build_model, chat_text
from harness_poc.core.skill_context import SkillResult

if TYPE_CHECKING:
    from harness_poc.core.llm_client import Message
    from harness_poc.core.skill_context import SkillContext

# Approximate chars-per-token for budget enforcement (no tiktoken dependency).
_CHARS_PER_TOKEN = 4

# Map sections in eviction priority order (lowest priority evicted first).
_SECTION_PRIORITY = [
    "parsing_schema",
    "reusable_results",
    "domain_constants",
    "context_understanding",
    "context_roadmap",
]


def execute(ctx: SkillContext, arguments: dict[str, Any]) -> SkillResult:
    corpus_key = str(arguments.get("corpus_key") or "").strip()
    if not corpus_key:
        return SkillResult(status="failed", content="Missing required argument: corpus_key", artifacts={})

    max_event_tokens = int(arguments.get("max_event_tokens") or 8000)
    token_budget = int(arguments.get("token_budget") or 1024)

    db = ctx.database  # type: ignore[union-attr]
    pending = db.get_pending_context_map_events(corpus_key, limit=50)
    if not pending:
        return SkillResult(
            status="success",
            content=f"No pending events for {corpus_key}.",
            artifacts={"corpus_key": corpus_key, "events_processed": 0},
        )

    current_map: dict[str, Any] = db.get_context_map(corpus_key) or {}
    model = build_model(ctx.config.llm)

    # --- Distiller pass ---
    events_payload = _truncate_events(pending, max_event_tokens)
    try:
        distiller_raw = chat_text(
            _distiller_messages(events_payload, current_map),
            model=model,
        )
        distiller_output = _parse_json(distiller_raw)
    except Exception as exc:  # noqa: BLE001
        return SkillResult(status="failed", content=f"Distiller failed: {exc}", artifacts={})

    # --- Cartographer pass ---
    try:
        cartographer_raw = chat_text(
            _cartographer_messages(distiller_output, current_map),
            model=model,
        )
        cartographer_output = _parse_json(cartographer_raw)
    except Exception as exc:  # noqa: BLE001
        return SkillResult(status="failed", content=f"Cartographer failed: {exc}", artifacts={})

    edits: list[dict[str, Any]] = cartographer_output.get("edits") or []

    # --- Apply edits ---
    updated_map = _apply_edits(current_map, edits)

    # --- Evictor ---
    updated_map = _enforce_budget(updated_map, token_budget)

    # --- Token count ---
    map_text = json.dumps(updated_map, sort_keys=True)
    token_count = len(map_text) // _CHARS_PER_TOKEN

    # --- Atomic write ---
    event_ids = [row.event_id for row in pending]
    db.write_map_and_mark_processed(corpus_key, updated_map, token_count, event_ids)

    return SkillResult(
        status="success",
        content=(
            f"Materialized {len(event_ids)} event(s) for {corpus_key}. "
            f"Map now ~{token_count} tokens."
        ),
        artifacts={
            "corpus_key": corpus_key,
            "events_processed": len(event_ids),
            "token_count": token_count,
            "edits_applied": len(edits),
        },
    )


# ── Helpers ──────────────────────────────────────────────────────────────────


def _truncate_events(rows: list[Any], max_event_tokens: int) -> list[dict[str, Any]]:
    """Return as many events as fit within the token budget, newest last."""
    budget_chars = max_event_tokens * _CHARS_PER_TOKEN
    result: list[dict[str, Any]] = []
    used = 0
    for row in rows:
        serialized = row.payload
        if used + len(serialized) > budget_chars:
            break
        result.append(json.loads(serialized))
        used += len(serialized)
    return result


def _distiller_messages(
    events: list[dict[str, Any]],
    current_map: dict[str, Any],
) -> list[Message]:
    return [
        {
            "role": "system",
            "content": (
                "You are a Context Map Distiller. Examine a batch of interaction events "
                "from an agent working with a recurring external context. Determine what "
                "the agent learned about the context itself (not the task), and produce "
                "structured output.\n\n"
                "Output format: JSON with keys \"diagnosis\" (string), "
                "\"tags\" (object mapping entry_key to one of: helpful/harmful/neutral/stale), "
                "and \"observations\" (list of plain-language orientation facts).\n\n"
                "IMPORTANT: Do not assign sections or priority scores in observations — "
                "those are Cartographer outputs. Record only what was learned."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Current context map:\n{json.dumps(current_map, indent=2)}\n\n"
                f"Unprocessed events:\n{json.dumps(events, indent=2)}\n\n"
                "Produce the JSON output now."
            ),
        },
    ]


def _cartographer_messages(
    distiller_output: dict[str, Any],
    current_map: dict[str, Any],
) -> list[Message]:
    return [
        {
            "role": "system",
            "content": (
                "You are a Context Map Cartographer. Translate distilled observations into "
                "structured map edits.\n\n"
                "Sections: context_roadmap, context_understanding, domain_constants, "
                "reusable_results, parsing_schema.\n\n"
                "Output format: JSON with key \"edits\", each edit having:\n"
                "  op (ADD|DELETE|REPLACE), section, entry_key (string slug), "
                "content (string), priority_score (0.0–1.0), supporting_event_ids (list).\n\n"
                "Also DELETE any entry tagged 'harmful' or 'stale' by the Distiller."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Distiller output:\n{json.dumps(distiller_output, indent=2)}\n\n"
                f"Current context map:\n{json.dumps(current_map, indent=2)}\n\n"
                "Produce the JSON edits now."
            ),
        },
    ]


def _apply_edits(
    current_map: dict[str, Any],
    edits: list[dict[str, Any]],
) -> dict[str, Any]:
    """Apply ADD/DELETE/REPLACE edits to the map. Map structure: {section: {entry_key: {content, priority_score}}}."""
    result: dict[str, Any] = {section: dict(current_map.get(section) or {}) for section in _SECTION_PRIORITY}
    for edit in edits:
        op = str(edit.get("op") or "").upper()
        section = str(edit.get("section") or "")
        entry_key = str(edit.get("entry_key") or "")
        if not section or not entry_key or section not in result:
            continue
        if op == "DELETE":
            result[section].pop(entry_key, None)
        elif op in ("ADD", "REPLACE"):
            result[section][entry_key] = {
                "content": str(edit.get("content") or ""),
                "priority_score": float(edit.get("priority_score") or 0.5),
            }
    return result


def _enforce_budget(
    map_data: dict[str, Any],
    token_budget: int,
) -> dict[str, Any]:
    """Evict lowest-priority entries until map fits within token_budget."""
    char_budget = token_budget * _CHARS_PER_TOKEN
    while len(json.dumps(map_data, sort_keys=True)) > char_budget:
        evicted = False
        for section in _SECTION_PRIORITY:
            entries = map_data.get(section) or {}
            if not entries:
                continue
            lowest_key = min(entries, key=lambda k: entries[k].get("priority_score", 0.0))
            del map_data[section][lowest_key]
            evicted = True
            break
        if not evicted:
            break
    return map_data


def _parse_json(raw: str) -> dict[str, Any]:
    """Parse LLM output as JSON. Strips markdown fences if present."""
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    result = json.loads(text)
    if not isinstance(result, dict):
        msg = f"Expected JSON object, got {type(result).__name__}"
        raise ValueError(msg)
    return result
```

---

### 1.7 Update `BlackboardAccessProxy`

**File: `harness_poc/core/blackboard_proxy.py`**

The proxy uses an explicit whitelist — every `BlackboardDatabase` method used by skills must
be mirrored here. Add the following five methods. The read methods call `_require_read()`;
the write methods call `_require_write()`.

```python
# --- context map read methods ---

def get_context_map(self, corpus_key: str) -> dict[str, Any] | None:
    self._require_read()
    return self._db.get_context_map(corpus_key)

def get_pending_context_map_events(
    self, corpus_key: str, limit: int = 50
) -> list[Any]:
    self._require_read()
    return self._db.get_pending_context_map_events(corpus_key, limit)

def get_pending_corpus_keys(self) -> list[str]:
    self._require_read()
    return self._db.get_pending_corpus_keys()

# --- context map write methods ---

def append_context_map_event(self, event: Any) -> None:
    self._require_write()
    self._db.append_context_map_event(event)

def write_map_and_mark_processed(
    self,
    corpus_key: str,
    map_json: dict[str, Any],
    token_count: int,
    event_ids: list[str],
) -> None:
    self._require_write()
    self._db.write_map_and_mark_processed(corpus_key, map_json, token_count, event_ids)
```

Add `from typing import Any` to imports if not already present.

---

### 1.8 Tests for Phase 1

**New file: `tests/test_context_map.py`**

Cover:

1. `append_context_map_event` inserts a row; `get_pending_context_map_events` returns it.
2. `write_map_and_mark_processed` writes the map and marks events `processed=1` atomically.
3. `get_pending_corpus_keys` returns only corpus keys with unprocessed events.
4. `get_context_map` returns `None` for unknown corpus, parsed dict for known.
5. `execute` in `append_event/skill.py` rejects unknown `event_type`.
6. `execute` in `append_event/skill.py` succeeds with valid `EntityReferenced` payload.
7. `_apply_edits` with ADD, DELETE, REPLACE operations.
8. `_enforce_budget` evicts lowest-priority entries until under budget.
9. `_parse_json` strips markdown fences and parses correctly.

Use `sqlite:///` in-memory databases (same pattern as existing tests). Mock `chat_text` for
the materializer skill tests (do not make real LLM calls).

---

## Phase 2 — Harness Integration

**Goal:** Events are emitted automatically; context map is injected into the system prompt.

### 2.1 Inject context map into system prompt

**File: `harness_poc/app_factory.py`**

In `build_app_state()`, after `project_state = database.ensure_project_state()`, add:

```python
corpus_key = f"{config.project_id}:default"
context_map = database.get_context_map(corpus_key)
context_map_block = ""
if context_map:
    context_map_block = f"\n\n--- Context Map ---\n{json.dumps(context_map, indent=2)}\n---"
```

Then append `context_map_block` to `full_system_prompt`:

```python
full_system_prompt = "\n\n".join(
    filter(None, [
        system_prompt,
        build_state_context(project_state, session_state),
        context_map_block.strip() or None,
    ])
)
```

> The `corpus_key` in Phase 2 is hardcoded to `"default"` for simplicity. Phase 3 can
> make it dynamic based on which tools are active in the session.

### 2.2 Emit `DocumentRetrieved` events from search skill

**File: `skills/search_documents/skill.py`**

After a successful search result is returned, call:

```python
ctx.database.append_context_map_event(
    DocumentRetrieved(
        session_id=ctx.session_id,
        corpus_key=f"{ctx.config.project_id}:codebase",
        query=query,
        retrieved_doc_ids=[hit["id"] for hit in hits],
        retrieved_doc_titles=[hit.get("title", "") for hit in hits],
        retrieval_strategy=mode,
    )
)
```

Import `DocumentRetrieved` from `harness_poc.core.context_map_events`. Add the import at the
top of the file.

### 2.3 Emit `SearchFailed` events from search skill

In the error path of `skills/search_documents/skill.py`, emit:

```python
ctx.database.append_context_map_event(
    SearchFailed(
        session_id=ctx.session_id,
        corpus_key=f"{ctx.config.project_id}:codebase",
        attempted_query=query,
        strategy=mode,
        error=str(exc),
    )
)
```

---

## Phase 3 — Async Background Runner

**Goal:** `MaterializerRunner` polls in the background; no manual invocation required.

### 3.1 Create `MaterializerRunner`

**New file: `harness_poc/core/materializer_runner.py`**

```python
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from harness_poc.core.config import HarnessConfig
    from harness_poc.core.database import BlackboardDatabase
    from harness_poc.core.skill_runner import SkillRunner

logger = logging.getLogger(__name__)


class MaterializerRunner:
    def __init__(
        self,
        db: BlackboardDatabase,
        skill_runner: SkillRunner,
        config: HarnessConfig,
        poll_interval: float = 30.0,
    ) -> None:
        self._db = db
        self._skill_runner = skill_runner
        self._config = config
        self._poll_interval = poll_interval

    async def run_forever(self) -> None:
        while True:
            try:
                await self._poll_once()
            except Exception:  # noqa: BLE001
                logger.exception("MaterializerRunner: unhandled error in poll cycle")
            await asyncio.sleep(self._poll_interval)

    async def _poll_once(self) -> None:
        corpus_keys = self._db.get_pending_corpus_keys()
        for corpus_key in corpus_keys:
            await self._materialize(corpus_key)

    async def _materialize(self, corpus_key: str) -> None:
        result = self._skill_runner.execute_skill(
            "context-map-materializer",
            {"corpus_key": corpus_key},
            session_id="materializer",
        )
        if result.status != "success":
            logger.warning("Materializer failed for %s: %s", corpus_key, result.content)
```

> `SkillRunner.run_skill` — verify this is the correct call signature by checking
> `harness_poc/core/skill_runner.py`. Adjust if the method name or signature differs.

### 3.2 Add config knobs

**File: `harness.yaml`** — add under `runtime:`:

```yaml
  materializer_poll_interval: 30
  materializer_max_event_tokens: 8000
  materializer_token_budget: 1024
```

**File: `harness_poc/core/config.py`** — add to `RuntimeConfig`:

```python
materializer_poll_interval: float = 30.0
materializer_max_event_tokens: int = 8000
materializer_token_budget: int = 1024
```

Load in `HarnessConfig.load()`:

```python
materializer_poll_interval=float(runtime_raw.get("materializer_poll_interval", 30.0)),
materializer_max_event_tokens=int(runtime_raw.get("materializer_max_event_tokens", 8000)),
materializer_token_budget=int(runtime_raw.get("materializer_token_budget", 1024)),
```

### 3.3 Start `MaterializerRunner` in app factory

**File: `harness_poc/app_factory.py`** — `MaterializerRunner` is an async background task.
Start it when the TUI or REPL event loop is running.

The cleanest hook is the `AppState` dataclass. Add an optional field:

```python
materializer_runner: MaterializerRunner | None = None
```

In `build_app_state()`:

```python
from harness_poc.core.materializer_runner import MaterializerRunner  # noqa: PLC0415

materializer = MaterializerRunner(
    db=database,
    skill_runner=skill_runner,
    config=config,
    poll_interval=config.runtime.materializer_poll_interval,
)
```

Store it in `AppState`. In `tui.py` and `repl.py`, schedule `asyncio.create_task(app_state.materializer_runner.run_forever())` after the event loop is running.

---

## Summary of all files changed / created

| File | Action |
|------|--------|
| `harness.yaml` | Add `project.id`, materializer knobs |
| `harness_poc/core/config.py` | Add `project_id`, materializer knobs |
| `harness_poc/core/context_map_events.py` | **Create** — Pydantic event models |
| `harness_poc/core/models.py` | Add `DbContextMapEvent`, `DbContextMap` |
| `harness_poc/core/database.py` | Add 5 context map methods |
| `harness_poc/core/blackboard_proxy.py` | Add 5 context map delegation methods |
| `harness_poc/system_skills/append_event/SKILL.md` | **Create** |
| `harness_poc/system_skills/append_event/skill.py` | **Create** |
| `skills/context-map-materializer/SKILL.md` | **Create** |
| `skills/context-map-materializer/skill.py` | **Create** |
| `harness_poc/app_factory.py` | Inject context map into system prompt (Phase 2); wire runner (Phase 3) |
| `skills/search_documents/skill.py` | Emit `DocumentRetrieved` / `SearchFailed` events (Phase 2) |
| `harness_poc/core/materializer_runner.py` | **Create** — background poll loop (Phase 3) |
| `tests/test_context_map.py` | **Create** — Phase 1 unit tests |

---

## Acceptance criteria

### Phase 1

- `uv run pytest tests/test_context_map.py` passes with all 9 tests.
- `uv run harness-poc skill list` shows `append_event` and `context-map-materializer`.
- Running `/skill append_event` with a valid payload inserts a row into `context_map_events`.
- Running `/skill context-map-materializer corpus_key=deverino:codebase` after appending events
  writes a row to `context_map` and marks events `processed=1`.

### Phase 2

- After 3+ document searches, the system prompt contains a `--- Context Map ---` block.

### Phase 3

- `MaterializerRunner` starts with the REPL/TUI and logs materialization activity every
  `materializer_poll_interval` seconds when unprocessed events are present.
