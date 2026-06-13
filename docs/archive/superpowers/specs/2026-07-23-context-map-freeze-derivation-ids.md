# Context Map: Freeze, Derivation Events & Stable IDs

**Date:** 2026-07-23
**Status:** revised-after-review
**Design ref:** `docs/superpowers/specs/2026-05-20-event-sourced-context-map-design.md`
**Target:** autonomous implementation agent

---

## Overview

Three targeted patches on the existing context-map materializer
(`skills/context-map-materializer/skill.py`). Each is independently
deployable. All follow the conventions from the Phase 1–3 spec: Python 3.12,
`from __future__ import annotations`, Ruff 100-char double-quote, no
comments unless the WHY is non-obvious.

| # | Patch | Impact | LLM cost savings | Audit trail |
|---|-------|--------|-----------------|-------------|
| 1 | **Freeze mechanism** | Materializer skips poll cycles when map is stable | ~2 LLM calls per skipped cycle | No |
| 2 | **Derivation event emission** | Evictions and promotions produce events | No | Yes |
| 3 | **Stable entry IDs** | Entries get `entry_id` (UUID) alongside slug | No | Yes |

---

## Patch 1 — Freeze Mechanism

**Problem:** Every poll cycle runs two LLM calls (Distiller + Cartographer)
even when the map hasn't changed. PEEK uses *m* = 3 consecutive
no-change cycles before freezing.

### 1.1 Add freeze config fields

**File:** `harness_poc/core/config.py` — add to `RuntimeConfig`:

```python
materializer_freeze_threshold: int = 3
materializer_freeze_seconds: int = 300
```

Also update `HarnessConfig.load()` so the manual `RuntimeConfig(...)`
construction reads both values from `runtime_raw`:

```python
materializer_freeze_threshold=int(runtime_raw.get("materializer_freeze_threshold", 3)),
materializer_freeze_seconds=int(runtime_raw.get("materializer_freeze_seconds", 300)),
```

**File:** `harness.yaml` — add:

```yaml
  materializer_freeze_threshold: 3
  materializer_freeze_seconds: 300
```

### 1.2 Add `freeze_until` to `DbContextMap`

**File:** `harness_poc/core/models.py` — add column:

```python
freeze_until: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
```

Use the same ISO-8601 string convention as the existing context-map event
timestamps. Do not use `Column(DateTime)` unless the implementation changes
all freeze code to store and compare `datetime` objects.

**Existing database compatibility:** `SQLModel.metadata.create_all()` does not
add columns to an existing PostgreSQL table. Add a lightweight migration/schema
repair step before acceptance, for example:

```sql
ALTER TABLE context_map ADD COLUMN IF NOT EXISTS freeze_until TEXT;
```

For tests, in-memory SQLite is created from fresh metadata and needs no
migration.

### 1.3 Add DB methods

**File:** `harness_poc/core/database.py`

```python
def is_map_frozen(self, corpus_key: str, now: str | None = None) -> bool:
    """Return True if the map has a freeze_until that hasn't expired."""
    if now is None:
        now = self._utc_now()
    with Session(self._engine) as session:
        row = session.get(DbContextMap, corpus_key)
    if row is None or row.freeze_until is None:
        return False
    return row.freeze_until > now


def set_map_freeze(self, corpus_key: str, freeze_until: str) -> None:
    with Session(self._engine) as session:
        row = session.get(DbContextMap, corpus_key)
        if row is not None:
            row.freeze_until = freeze_until
            session.add(row)
            session.commit()
```

The string comparison is valid because `_utc_now()` and `freeze_until` both use
UTC ISO strings with the same format and timezone suffix.

### 1.4 Update `write_map_and_mark_processed`

**File:** `harness_poc/core/database.py` — add `freeze_until` parameter
(default `None`) and store it on the `DbContextMap` row inside the method.

```python
def write_map_and_mark_processed(
    self,
    corpus_key: str,
    map_json: dict[str, Any],
    token_count: int,
    event_ids: list[str],
    freeze_until: str | None = None,
) -> None:
```

When creating or updating the `DbContextMap` row inside this method, set
`row.freeze_until = freeze_until`. This intentionally clears an expired freeze
when the map is successfully rewritten.

Also update `BlackboardAccessProxy.write_map_and_mark_processed()` to accept
and forward the optional `freeze_until` argument. The context-map materializer
calls the database through this proxy.

### 1.5 Track staleness in `MaterializerRunner`

**File:** `harness_poc/core/materializer_runner.py`

Add an instance variable:

```python
class MaterializerRunner:
    def __init__(self, ...):
        ...
        self._no_change_count: dict[str, int] = {}
```

After the skill executes in `_materialize`, check whether the map actually
changed. The materializer skill must report `map_changed: bool` in its result
artifacts. Do not use the raw number of edits returned by the LLM: invalid
edits, DELETEs for missing entries, and no-op REPLACEs are not real changes.

If `map_changed` is false, increment the counter; if true, reset it. When the
counter reaches `materializer_freeze_threshold`, freeze the map.

```python
async def _materialize(self, corpus_key: str) -> None:
    result = await asyncio.to_thread(
        self._skill_runner.execute_skill,
        "context-map-materializer",
        {...},
        "materializer",
    )
    if result.status != "success":
        logger.warning("Materializer failed for %s: %s", corpus_key, result.content)
        return

    map_changed = bool(result.artifacts.get("map_changed", True))
    if not map_changed:
        self._no_change_count[corpus_key] = (
            self._no_change_count.get(corpus_key, 0) + 1
        )
    else:
        self._no_change_count[corpus_key] = 0

    threshold = self._config.runtime.materializer_freeze_threshold
    if self._no_change_count[corpus_key] >= threshold:
        freeze_until = (
            datetime.now(tz=UTC)
            + timedelta(seconds=self._config.runtime.materializer_freeze_seconds)
        ).isoformat(timespec="seconds")
        self._db.set_map_freeze(corpus_key, freeze_until)
        logger.info("Froze map for %s until %s", corpus_key, freeze_until)
```

When freezing, leave pending events unprocessed. They should accumulate until
`freeze_until` expires.

### 1.6 Skip frozen corpora on poll

**File:** `harness_poc/core/materializer_runner.py` — in `_poll_once`:

```python
async def _poll_once(self) -> None:
    corpus_keys = self._db.get_pending_corpus_keys()
    now = datetime.now(tz=UTC).isoformat(timespec="seconds")
    for corpus_key in corpus_keys:
        if self._db.is_map_frozen(corpus_key, now):
            continue
        await self._materialize(corpus_key)
```

### 1.7 Tests

**File:** `tests/test_context_map.py`

- `test_is_map_frozen_returns_true_when_frozen()` — set `freeze_until` to a
  future timestamp, assert `True`.
- `test_is_map_frozen_returns_false_when_expired()` — set `freeze_until` to a
  past timestamp, assert `False`.
- `test_materializer_skips_frozen_corpus()` — mock `is_map_frozen` to return
  `True`, verify `_materialize` is not called for that corpus.
- `test_materializer_freezes_after_three_no_change_cycles()` — make the skill
  runner return `{"map_changed": False}` three times and assert
  `set_map_freeze()` is called.

---

## Patch 2 — Derivation Event Emission

**Problem:** `_enforce_budget` silently deletes entries. The
`MapEntryPromoted` and `MapEntryEvicted` event models exist at
`harness_poc/core/context_map_events.py` but are never instantiated or
written to the event store.

Derivation events should also carry the stable ID of the affected entry once
Patch 3 is present:

```python
class MapEntryPromoted(ContextMapEvent):
    event_type: Literal["map_entry_promoted"] = "map_entry_promoted"
    entry_id: str | None = None
    entry_key: str
    from_section: str
    to_section: str


class MapEntryEvicted(ContextMapEvent):
    event_type: Literal["map_entry_evicted"] = "map_entry_evicted"
    entry_id: str | None = None
    entry_key: str
    section: str
    reason: str
```

### 2.1 Pass `session_id` to the materializer skill

**File:** `harness_poc/core/materializer_runner.py`

The `MaterializerRunner` needs a session ID for derivation events. Add it
to the constructor:

```python
class MaterializerRunner:
    def __init__(
        self,
        db: BlackboardDatabase,
        skill_runner: SkillRunner,
        config: HarnessConfig,
        session_id: str,
        poll_interval: float = 30.0,
    ) -> None:
```

Pass it through when invoking the skill:

```python
result = await asyncio.to_thread(
    self._skill_runner.execute_skill,
    "context-map-materializer",
    {
        "corpus_key": corpus_key,
        "max_event_tokens": self._config.runtime.materializer_max_event_tokens,
        "token_budget": self._config.runtime.materializer_token_budget,
        "session_id": self._session_id,
    },
    "materializer",
)
```

**File:** `harness_poc/app_factory.py` — pass `session_id` when constructing:

```python
materializer = MaterializerRunner(
    db=database,
    skill_runner=skill_runner,
    config=config,
    session_id=session_id,
    poll_interval=config.runtime.materializer_poll_interval,
)
```

### 2.2 Split `_enforce_budget` return value

**File:** `skills/context-map-materializer/skill.py`

Change `_enforce_budget` to return both the trimmed map and a list of
evicted entries:

```python
def _enforce_budget(
    map_data: dict[str, Any],
    token_budget: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Returns (trimmed_map, evictions).

    Each eviction dict has keys: entry_id, entry_key, section, priority_score.
    """
    evictions: list[dict[str, Any]] = []
    char_budget = token_budget * _CHARS_PER_TOKEN
    while len(json.dumps(map_data, sort_keys=True)) > char_budget:
        evicted = False
        for section in reversed(_SECTION_PRIORITY):
            entries = map_data.get(section) or {}
            if not entries:
                continue
            lowest_key = min(
                entries, key=lambda k: entries[k].get("priority_score", 0.0)
            )
            evictions.append({
                "entry_id": entries[lowest_key].get("entry_id"),
                "entry_key": lowest_key,
                "section": section,
                "priority_score": entries[lowest_key].get("priority_score", 0.0),
            })
            del map_data[section][lowest_key]
            evicted = True
            break
        if not evicted:
            break
    return map_data, evictions
```

Update the call site in `execute()`:

```python
updated_map, evictions = _enforce_budget(updated_map, token_budget)
```

If Patch 3 is applied first or in the same change set, the final implementation
uses the Patch 3 variable names shown later:
`candidate_map, applied_count = _apply_edits(...)` followed by
`updated_map, evictions = _enforce_budget(candidate_map, token_budget)`.

`_SECTION_PRIORITY` is ordered highest to lowest priority:
`parsing_schema`, `reusable_results`, `domain_constants`,
`context_understanding`, `context_roadmap`. Budget enforcement must iterate it
in reverse so low-priority sections are evicted before high-priority sections.

### 2.3 Emit derivation events in `execute()`

**File:** `skills/context-map-materializer/skill.py`

After the Cartographer step, before writing the map, collect evictions and
promotions, then write derivation events to the event store.

```python
session_id = str(arguments.get("session_id") or "materializer")
derivation_events: list[ContextMapEvent] = []

for ev in evictions:
    derivation_events.append(
        MapEntryEvicted(
            session_id=session_id,
            corpus_key=corpus_key,
            entry_id=ev.get("entry_id"),
            entry_key=ev["entry_key"],
            section=ev["section"],
            reason=f"budget_eviction (priority={ev['priority_score']})",
        )
    )

promotions = _detect_promotions(current_map, updated_map)
for prom in promotions:
    derivation_events.append(
        MapEntryPromoted(
            session_id=session_id,
            corpus_key=corpus_key,
            entry_id=prom.get("entry_id"),
            entry_key=prom["entry_key"],
            from_section=prom["from_section"],
            to_section=prom["to_section"],
        )
    )

for event in derivation_events:
    db.append_context_map_event(event)
```

Place this block **before** the `write_map_and_mark_processed` call so
derivation events are written in the same materializer cycle. They'll be
picked up by the next poll.

Do not mark derivation events processed in the same `write_map_and_mark_processed`
call. Only mark the source `pending` event IDs processed; the new derivation
events must remain pending for the next materializer pass.

### 2.4 Add `_detect_promotions` helper

```python
def _detect_promotions(
    old: dict[str, Any],
    new: dict[str, Any],
) -> list[dict[str, Any]]:
    """Detect entries that moved to a higher-priority section."""
    promotions: list[dict[str, Any]] = []
    old_sections = {k: set(v or {}) for k, v in old.items()}
    new_sections = {k: set(v or {}) for k, v in new.items()}
    for new_sec_idx, new_sec in enumerate(_SECTION_PRIORITY):
        if new_sec not in new_sections:
            continue
        for entry_key in new_sections[new_sec]:
            for old_sec_idx, old_sec in enumerate(_SECTION_PRIORITY):
                if (
                    old_sec in old_sections
                    and entry_key in old_sections[old_sec]
                ):
                    if new_sec_idx < old_sec_idx:
                        promotions.append({
                            "entry_id": new[new_sec][entry_key].get("entry_id"),
                            "entry_key": entry_key,
                            "from_section": old_sec,
                            "to_section": new_sec,
                        })
                    break
    return promotions
```

### 2.5 Add imports

**File:** `skills/context-map-materializer/skill.py`

```python
from harness_poc.core.context_map_events import (
    ContextMapEvent,
    MapEntryEvicted,
    MapEntryPromoted,
)
```

### 2.6 Tests

**File:** `tests/test_context_map.py`

- `test_enforce_budget_returns_evictions()` — pass a map over budget,
  verify the evictions list is non-empty and contains expected keys.
- `test_detect_promotions_detects_upward_moves()` — move an entry from
  `context_roadmap` to `domain_constants`, assert one promotion returned.
- `test_materializer_emits_derivation_events()` — full integration:
  append events, materialize with budget pressure, verify
  `MapEntryEvicted` rows appear in the event store.
- Mock `chat_text` in materializer integration tests. These tests must not make
  real network/model calls.

---

## Patch 3 — Stable Entry IDs

**Problem:** Entry keys are human-readable slugs (`skill_runner`,
`db_connection`). If content changes enough that the slug changes, references
that point only at the slug can break. PEEK uses `[cr-00001]`-style stable IDs.

This patch adds stable IDs to every entry and to derivation audit events. It
does not replace slug-based edit targeting in this phase. Future callers that
need durable cross-query references should store `entry_id`, not only
`entry_key`. Slug rename support is explicitly out of scope for this patch.

### 3.1 Entry structure change

Current format:

```json
{"content": "...", "priority_score": 0.7}
```

New format:

```json
{"entry_id": "a1b2c3d4", "content": "...", "priority_score": 0.7}
```

`entry_id` is a random 8-char hex string. It is assigned when an entry is
first created (ADD op) and retained across REPLACE operations. DELETE
followed by ADD gets a new ID.

Before applying edits, normalize the loaded current map so every existing entry
has an `entry_id`. This makes the acceptance criterion true for old maps, not
only for entries touched by ADD/REPLACE.

```python
def _ensure_entry_ids(map_data: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for section in _SECTION_PRIORITY:
        entries = dict(map_data.get(section) or {})
        result[section] = {}
        for entry_key, entry in entries.items():
            if isinstance(entry, dict):
                next_entry = dict(entry)
            else:
                next_entry = {"content": str(entry)}
            next_entry.setdefault("entry_id", _generate_entry_id())
            result[section][entry_key] = next_entry
    return result
```

### 3.2 Modify `_apply_edits`

**File:** `skills/context-map-materializer/skill.py`

```python
def _apply_edits(
    current_map: dict[str, Any],
    edits: list[dict[str, Any]],
) -> tuple[dict[str, Any], int]:
    result = _ensure_entry_ids(current_map)
    applied_count = 0
    for edit in edits:
        op = str(edit.get("op") or "").upper()
        section = str(edit.get("section") or "")
        entry_key = str(edit.get("entry_key") or "")
        if not section or not entry_key or section not in result:
            continue
        if op == "DELETE":
            if entry_key in result[section]:
                del result[section][entry_key]
                applied_count += 1
        elif op in ("ADD", "REPLACE"):
            existing = result[section].get(entry_key)
            if op == "ADD" or existing is None:
                entry_id = _generate_entry_id()
            else:
                entry_id = existing.get("entry_id") or _generate_entry_id()
            next_entry = {
                "entry_id": entry_id,
                "content": str(edit.get("content") or ""),
                "priority_score": float(edit.get("priority_score") or 0.5),
            }
            if result[section].get(entry_key) != next_entry:
                result[section][entry_key] = next_entry
                applied_count += 1
    return result, applied_count
```

Update `execute()` accordingly:

```python
candidate_map, applied_count = _apply_edits(current_map, edits)
updated_map, evictions = _enforce_budget(candidate_map, token_budget)
map_changed = updated_map != current_map
```

Return both `edits_applied` and `map_changed` in `SkillResult.artifacts`.
`edits_applied` should mean "validated edits that changed the in-memory map
before budget enforcement", not raw LLM edit count.

`map_changed` should compare against the original loaded `current_map`, so
adding missing IDs to old entries counts as a real persisted map change.

### 3.3 Add `_generate_entry_id`

```python
import uuid


def _generate_entry_id() -> str:
    return uuid.uuid4().hex[:8]
```

### 3.4 Update `_enforce_budget` evictions

Eviction dicts should include the `entry_id` from the evicted entry:

```python
evictions.append({
    "entry_id": entries[lowest_key].get("entry_id"),
    "entry_key": lowest_key,
    "section": section,
    "priority_score": entries[lowest_key].get("priority_score", 0.0),
})
```

### 3.5 No map JSON migration

The map is stored as JSON in `map_json` (TEXT column). Old entries without
`entry_id` are handled by `_ensure_entry_ids()` on the next materializer pass.
There is no separate migration for existing `map_json` payloads.

This does not remove the Patch 1 database migration for `context_map.freeze_until`.

### 3.6 Tests

**File:** `tests/test_context_map.py`

- `test_apply_edits_add_assigns_entry_id()` — verify an ADD operation
  produces an 8-char hex `entry_id`.
- `test_apply_edits_replace_retains_entry_id()` — verify a REPLACE keeps
  the same `entry_id` as the existing entry.
- `test_ensure_entry_ids_handles_old_format_entries()` — verify old-format
  entries with no `entry_id` get a new ID during normalization.
- `test_apply_edits_reports_no_change_for_missing_delete()` — verify a DELETE
  for a missing entry does not increment `edits_applied`.
- `test_execute_reports_map_changed_false_for_noop_edits()` — mock both LLM
  calls so the Cartographer returns no effective changes, then assert the
  result artifact has `map_changed is False`.

---

## File Change Summary

| File | Action |
|------|--------|
| `harness_poc/core/config.py` | Add `materializer_freeze_threshold`, `materializer_freeze_seconds` |
| `harness.yaml` | Add freeze defaults |
| `harness_poc/core/models.py` | Add `freeze_until` TEXT column to `DbContextMap` |
| `harness_poc/core/database.py` | Add `is_map_frozen()`, `set_map_freeze()`; update `write_map_and_mark_processed()` signature |
| `harness_poc/core/blackboard_proxy.py` | Forward optional `freeze_until` in `write_map_and_mark_processed()` |
| DB migration/startup repair | Add `context_map.freeze_until` for existing PostgreSQL databases |
| `harness_poc/core/context_map_events.py` | Add optional `entry_id` to `MapEntryEvicted` and `MapEntryPromoted` |
| `harness_poc/core/materializer_runner.py` | Track `_no_change_count`; skip frozen corpora; accept and pass `session_id` |
| `harness_poc/app_factory.py` | Pass `session_id` to `MaterializerRunner` |
| `skills/context-map-materializer/skill.py` | Emit derivation events; add `entry_id` to entries; update `_apply_edits` and `_enforce_budget` returns; add `_detect_promotions`, `_generate_entry_id` |
| `tests/test_context_map.py` | Add tests for all three patches |

---

## Acceptance Criteria

1. `uv run pytest tests/test_context_map.py` passes all existing + new tests.
2. Existing PostgreSQL databases get a `context_map.freeze_until` TEXT column
   without requiring a destructive reset.
3. After three consecutive no-change materializer cycles for a corpus, the map
   is frozen for 5 minutes. Pending events accumulate but are not processed.
4. No-change means the persisted map JSON is unchanged, not merely that the LLM
   returned zero edits.
5. When budget pressure evicts an entry, a `MapEntryEvicted` event appears
   in `context_map_events` and includes the entry's stable ID when available.
6. Budget eviction removes lower-priority sections before higher-priority
   sections.
7. When an entry moves to a higher-priority section, a `MapEntryPromoted`
   event appears in `context_map_events` and includes the entry's stable ID
   when available.
8. Every map entry has a stable 8-char `entry_id` that survives REPLACE
   operations.
