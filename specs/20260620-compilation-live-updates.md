---
title: "Real-Time Compilation Updates — SSE Stream with Per-Skill Instant Feedback"
date: 2026-06-20
status: draft
kind: spec
---

# Real-Time Compilation Updates — SSE Stream with Per-Skill Instant Feedback

## Objective

Replace the current polling-based compilation UI (`setInterval` at 2–5s intervals) with a Server-Sent Events stream that pushes per-skill compilation results to the dashboard in real time. Each skill card updates instantly when its compilation completes, and the aggregate progress bar reflects live counts without polling.

## Current State

**Backend** (`harness_poc/core/skills/skill_compiler.py`):
- Module-level `_compilation_progress: dict` tracks `{running, total, completed, errors}`.
- `compile_skill()` runs synchronously in a daemon thread, calling `set_compilation_progress()` after each skill.
- `get_compilation_status()` returns the dict — consumed by `GET /api/skills/progress`.

**Frontend** (`dashboard-ui/src/views/SkillsView.vue`):
- `useCompilationProgressStore` polls `GET /api/skills/progress` every 5s.
- `useSkillsStore` polls `GET /api/skills` every 15s.
- Per-skill compile (`compileOne`) runs a manual `setInterval` at 2s until the skill status changes.
- A `watch` on `progress.data?.running` triggers a full `store.fetch()` when compilation finishes.

**Existing SSE infrastructure**:
- `GET /api/events/stream` streams `UnifiedEvent` objects from the DB at 1s intervals (FastAPI `StreamingResponse`).
- `dashboard-ui/src/api/sse.ts` wraps `EventSource` with a `createEventStream()` factory.
- This stream is **not** used for compilation — it serves DB-level session events.

## Design Decision: SSE over WebSocket

| Criterion | SSE | WebSocket |
|-----------|-----|-----------|
| Direction | Server→client (sufficient) | Bidirectional (unnecessary) |
| Already in stack | Yes — `StreamingResponse` + `EventSource` | No |
| Reconnection | Built into `EventSource` | Manual |
| Complexity | ~50 lines backend, ~60 lines frontend | Requires `websockets` dep + state machine |
| Thread safety | `asyncio.Queue` bridge with fan-out | Same challenge |

**Decision**: SSE. The data flow is unidirectional (server pushes compilation events, client consumes). No client→server messages needed during streaming. `EventSource` auto-reconnects, which is useful if compilation runs longer than the initial connection.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│ Backend (FastAPI)                                       │
│                                                         │
│  POST /api/skills/compile                               │
│  ┌──────────────────────────────────────────┐           │
│  │ _compile_all()  [daemon thread]           │           │
│  │   try:                                    │           │
│  │     for skill in skills:                  │           │
│  │       bundle = compile_skill(sf, ...)     │           │
│  │       publish_compile_event({             │           │
│  │         event: "skill_compiled",          │           │
│  │         skill_name, status, contracts,... │           │
│  │       })                                  │           │
│  │       publish_compile_event({             │           │
│  │         event: "compilation_progress",    │           │
│  │         total, completed, errors          │           │
│  │       })                                  │           │
│  │   finally:                                │           │
│  │     set_compilation_progress(running=False)           │
│  │     publish_compile_event({event: "compilation_done"})│
│  └──────────────┬───────────────────────────┘           │
│                 │ publish_compile_event() [fan-out]      │
│         ┌───────▼────────┐                               │
│         │ _clients: set   │  (one queue per SSE client)  │
│         │  of asyncio.Queue                              │
│         └───────┬────────┘                               │
│                 │ await get()                            │
│  GET /api/skills/compile/stream                          │
│  ┌─────────────▼────────────────────────────┐           │
│  │ async event_generator():                  │           │
│  │   emit snapshot if compilation running    │           │
│  │   while not disconnected:                 │           │
│  │     event = await queue.get()             │           │
│  │     yield f"event: {event['event']}       │           │
│  │            data: {json}\n\n"             │           │
│  └──────────────────────────────────────────┘           │
└──────────────────────┬──────────────────────────────────┘
                       │ SSE (text/event-stream)
┌──────────────────────▼──────────────────────────────────┐
│ Frontend (Vue + Pinia)                                  │
│                                                         │
│  createCompilationStream()                              │
│  ┌──────────────────────────────────────────┐           │
│  │ EventSource → /api/skills/compile/stream  │           │
│  │   on "skill_compiled":                    │           │
│  │     skillsStore.patchSkill(name, data)    │           │
│  │   on "compilation_progress":              │           │
│  │     progressCounts = data                 │           │
│  │   on "compilation_done":                  │           │
│  │     compiling.value = false               │           │
│  │     store.fetch()  // final reconciliation│           │
│  │     stream.close()                        │           │
│  │   on "compilation_error":                 │           │
│  │     compileError.value = data.detail      │           │
│  │     stream.close()                        │           │
│  └──────────────────────────────────────────┘           │
│                                                         │
│  SkillsView.vue  [reactive, no polling]                 │
│  ┌──────────────────────────────────────────┐           │
│  │ Progress bar: reactive counts from events │           │
│  │ Skill cards: update in-place on event     │           │
│  │ No setInterval, no watch on running       │           │
│  └──────────────────────────────────────────┘           │
└─────────────────────────────────────────────────────────┘
```

## Event Schema

### `skill_compiled`

Emitted after each skill finishes compilation (success or failure). Mirrors
`SkillCompilationSummary` (dashboard.ts) so the frontend can directly patch
a store entry.

```json
{
  "event": "skill_compiled",
  "skill_name": "acdl-syntax",
  "skill_type": "tool",
  "version": "1.0",
  "compilation_status": "full",
  "contract_count": 3,
  "template_count": 1,
  "invoke_pattern_count": 0,
  "error_count": 0,
  "compiled_at": "2026-06-20T14:30:00Z",
  "contracts": [
    {
      "name": "validate_acdl",
      "description": "Validate an ACDL file against the schema",
      "input_count": 2,
      "output_count": 1,
      "precondition_count": 1,
      "error_condition_count": 2,
      "cancellation_behavior": "rollback"
    }
  ],
  "templates": [
    {
      "name": "validate_acdl",
      "kind": "shell",
      "template_preview": "acdl validate $input --schema $schema"
    }
  ],
  "compilation_errors": [],
  "aliases": ["validate-acdl"]
}
```

**Field notes**:
- `compiled_at` is an ISO 8601 string. The backend converts `SkillBundle.compiled_at`
  (a `float` from `time.time()`) via `datetime.fromtimestamp(ts, tz=UTC).isoformat()`.
- `skill_type`, `version`, and `aliases` come from the skill's frontmatter (parsed
  by `skill_runner.parse_skill_document()` → `doc.metadata`).
- On exception: `compilation_status` is `"rejected"`, `compilation_errors` contains
  the exception message, `contracts`/`templates` are empty arrays.

### `compilation_progress`

Emitted after each skill during batch compilation. Replaces polling of
`GET /api/skills/progress`.

```json
{
  "event": "compilation_progress",
  "total": 20,
  "completed": 7,
  "errors": 1,
  "running": true
}
```

`errors` counts unhandled exceptions (compiler crashes), not `rejected` skills.
The `rejected` count is derived from the skills list, not the progress event.

### `compilation_done`

Emitted when compilation exits (normal completion, early termination, or crash).
Always fires — guaranteed by a `try/finally` in the daemon thread.

```json
{
  "event": "compilation_done",
  "total": 20,
  "completed": 18,
  "errors": 2
}
```

### `compilation_error`

Emitted when compilation fails to start (model unavailable, already running, etc.).

```json
{
  "event": "compilation_error",
  "detail": "LLM model not available — check API keys and provider configuration"
}
```

## Implementation Plan

### Phase 1: Backend Fan-Out & Event Infrastructure

**File**: `harness_poc/core/skills/skill_compiler.py`

Add at module level (after the existing `_compilation_progress` dict, around line 59):

```python
import asyncio
from threading import Lock

# Per-client SSE queues for fan-out (one queue per connected browser tab).
# Bounded to 50 events — a slow client that falls behind gets pruned rather
# than allowing unbounded memory growth.
_clients: set[asyncio.Queue[dict[str, Any]]] = set()
_clients_lock = Lock()
_MAX_CLIENT_QUEUE = 50


def subscribe_compile_events() -> asyncio.Queue[dict[str, Any]]:
    """Register a new SSE client. Returns a bounded queue the client consumes from."""
    q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=_MAX_CLIENT_QUEUE)
    with _clients_lock:
        _clients.add(q)
    return q


def unsubscribe_compile_events(q: asyncio.Queue[dict[str, Any]]) -> None:
    """Remove a disconnected SSE client."""
    with _clients_lock:
        _clients.discard(q)


def publish_compile_event(event: dict[str, Any]) -> None:
    """Push an event to all connected SSE clients. Thread-safe.

    Called from daemon compilation threads (non-async).  Holds _clients_lock
    for the duration of the fan-out loop to prevent interleaving with
    subscribe/unsubscribe.  Contention is minimal because publish is
    infrequent (once per skill, not per token).
    """
    with _clients_lock:
        dead: list[asyncio.Queue[dict[str, Any]]] = []
        for q in _clients:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            _clients.discard(q)
```

**Thread safety note**: `asyncio.Queue.put_nowait()` is documented as thread-safe in
CPython 3.14.  This relies on the GIL — a free-threaded build would need an explicit
lock.  Acceptable for the current CPython deployment.

Also add a helper to build the `skill_compiled` event from a `SkillBundle`:

```python
def _build_skill_compiled_event(
    skill_name: str,
    bundle: SkillBundle,
) -> dict[str, Any]:
    """Convert a SkillBundle into a skill_compiled SSE event dict."""
    from datetime import datetime, timezone  # noqa: PLC0415

    compiled_at_iso = datetime.fromtimestamp(
        bundle.compiled_at, tz=timezone.utc
    ).isoformat()

    return {
        "event": "skill_compiled",
        "skill_name": skill_name,
        "skill_type": bundle.metadata.skill_type if bundle.metadata else "",
        "version": bundle.metadata.version if bundle.metadata else "",
        "compilation_status": bundle.status,
        "contract_count": len(bundle.contracts),
        "template_count": len(bundle.templates),
        "invoke_pattern_count": len(bundle.invoke_patterns),
        "error_count": len(bundle.errors),
        "compiled_at": compiled_at_iso,
        "contracts": [
            {
                "name": c.name,
                "description": c.description,
                "input_count": len(c.inputs),
                "output_count": len(c.outputs),
                "precondition_count": len(c.preconditions),
                "error_condition_count": len(c.error_conditions),
                "cancellation_behavior": c.cancellation_behavior,
            }
            for c in bundle.contracts
        ],
        "templates": [
            {
                "name": t.name,
                "kind": t.kind,
                "template_preview": t.template_preview,
            }
            for t in bundle.templates
        ],
        "compilation_errors": [str(e) for e in bundle.errors],
        "aliases": bundle.metadata.aliases if bundle.metadata else [],
    }
```

### Phase 2: Backend Route Changes

**File**: `harness_poc/api/routes.py`

#### 2a. Compile-all route — add event publishing and crash safety

Replace the current `_compile_all()` inner function (lines 220–240) with:

```python
def _compile_all() -> None:
    db = BlackboardDatabase(create_db_engine(config.runtime.database_url))
    runner = SkillRunner(database=db, config=config)
    total = len(skill_files)
    set_compilation_progress(total=total, running=True)
    completed = 0
    errors = 0
    try:
        for sf in skill_files:
            skill_name = sf.parent.name
            try:
                bundle = compile_skill(
                    sf,
                    skill_runner=runner,
                    force=True,
                    model=model,
                    compiler_config=config.compiler,
                )
                completed += 1
            except Exception as exc:
                errors += 1
                # Emit a rejected event so the frontend updates the card
                bundle = _rejected_bundle(sf, [str(exc)])
                bundle.compiled_at = time.time()
                completed += 1  # count as completed (rejected) not crashed
            # Per-skill event
            publish_compile_event(
                _build_skill_compiled_event(skill_name, bundle)
            )
            # Progress update
            publish_compile_event({
                "event": "compilation_progress",
                "total": total,
                "completed": completed,
                "errors": errors,
                "running": True,
            })
    finally:
        set_compilation_progress(running=False)
        publish_compile_event({
            "event": "compilation_done",
            "total": total,
            "completed": completed,
            "errors": errors,
        })
```

**Key changes**:
- `compile_skill()` return value is captured (was discarded before).
- Exception path emits `skill_compiled` with `rejected` status (was silent before).
- `try/finally` guarantees `compilation_done` always fires (prevents stuck UI).
- Both `skill_compiled` and `compilation_progress` emitted per skill.

Requires additional imports at the top of the route function:
```python
from harness_poc.core.skills.skill_compiler import (
    _build_skill_compiled_event,
    _rejected_bundle,
    publish_compile_event,
)
import time
```

#### 2b. TOCTOU fix — atomic running check

Replace the `already_running` check (lines 195–197):

```python
current = get_compilation_status()
if current.get("running"):
    return {"status": "already_running"}
```

With:

```python
# Use set_compilation_progress as atomic check-and-set to prevent
# dual compilation from concurrent POST requests.
status = get_compilation_status()
if status.get("running"):
    return {"status": "already_running"}
# Mark running before spawning the thread — the thread will set
# running=False in its finally block.
set_compilation_progress(running=True)
```

And remove the first `set_compilation_progress(total=total, running=True)` call
from `_compile_all()` (it's now set before thread spawn, and the thread updates
`total`/`completed`/`errors`).

#### 2c. Compile-one route — add event publishing and crash safety

Replace the current `_compile_one()` inner function (lines 288–297) with:

```python
def _compile_one() -> None:
    db = BlackboardDatabase(create_db_engine(config.runtime.database_url))
    runner = SkillRunner(database=db, config=config)
    try:
        bundle = compile_skill(
            skill_file,  # type: ignore[arg-type]
            skill_runner=runner,
            force=True,
            model=model,
            compiler_config=config.compiler,
        )
    except Exception as exc:
        bundle = _rejected_bundle(skill_file, [str(exc)])
        bundle.compiled_at = time.time()
    publish_compile_event(
        _build_skill_compiled_event(name, bundle)
    )
    # Signal completion so the frontend knows to close the stream
    publish_compile_event({
        "event": "compilation_done",
        "total": 1,
        "completed": 1,
        "errors": 1 if bundle.status == "rejected" else 0,
    })
```

Requires additional imports in the route function:
```python
from harness_poc.core.skills.skill_compiler import (
    _build_skill_compiled_event,
    _rejected_bundle,
    publish_compile_event,
)
import time
```

Also add a check to prevent single-skill compile from racing with a batch compile:

```python
# Prevent concurrent batch + single-skill compilation
status = get_compilation_status()
if status.get("running"):
    return {"status": "error", "detail": "A batch compilation is already in progress"}
```

#### 2d. SSE endpoint — with snapshot on connect

Add after the existing routes (before the last route if any, or at end of file):

```python
@router.get("/api/skills/compile/stream")
async def stream_compilation(request: Request) -> StreamingResponse:
    """Server-Sent Events stream of compilation progress.

    Emits a snapshot of current progress on connect (if compilation is running),
    then pushes per-skill events as they complete.  Multiple browser tabs each
    get their own queue via the fan-out in skill_compiler.py.
    """
    from harness_poc.core.skills.skill_compiler import (
        get_compilation_status,
        subscribe_compile_events,
        unsubscribe_compile_events,
    )

    queue = subscribe_compile_events()

    async def event_generator():
        try:
            # Snapshot on connect: if compilation is already running, emit
            # current progress so late-joining clients see the correct state.
            status = get_compilation_status()
            if status.get("running"):
                snapshot = {
                    "event": "compilation_progress",
                    "total": int(status.get("total", 0)),
                    "completed": int(status.get("completed", 0)),
                    "errors": int(status.get("errors", 0)),
                    "running": True,
                }
                yield f"event: compilation_progress\ndata: {json.dumps(snapshot)}\n\n"

            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=10.0)
                    yield (
                        f"event: {event['event']}\n"
                        f"data: {json.dumps(event, default=str)}\n\n"
                    )
                except asyncio.TimeoutError:
                    # Keepalive — prevents proxy/CDN from closing idle connection.
                    # 10s is safe for nginx (60s default), ALB (60s), Cloudflare (100s).
                    yield ": keepalive\n\n"
        finally:
            unsubscribe_compile_events(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
```

### Phase 3: Frontend Type Definitions

**File**: `dashboard-ui/src/types/dashboard.ts`

Add discriminated union types for compilation events:

```typescript
// ── Compilation SSE Events ───────────────────────────────────────────────────

export interface SkillCompiledEvent {
  event: 'skill_compiled'
  skill_name: string
  skill_type: string
  version: string
  compilation_status: string
  contract_count: number
  template_count: number
  invoke_pattern_count: number
  error_count: number
  compiled_at: string
  contracts: SkillContractSummary[]
  templates: SkillTemplateSummary[]
  compilation_errors: string[]
  aliases: string[]
}

export interface CompilationProgressEvent {
  event: 'compilation_progress'
  total: number
  completed: number
  errors: number
  running: boolean
}

export interface CompilationDoneEvent {
  event: 'compilation_done'
  total: number
  completed: number
  errors: number
}

export interface CompilationErrorEvent {
  event: 'compilation_error'
  detail: string
}

export type CompilationEvent =
  | SkillCompiledEvent
  | CompilationProgressEvent
  | CompilationDoneEvent
  | CompilationErrorEvent
```

### Phase 4: Frontend SSE Client

**New file**: `dashboard-ui/src/api/compilation-sse.ts`

```typescript
import type { CompilationEvent } from '@/types/dashboard'

export function createCompilationStream(
  onEvent: (event: CompilationEvent) => void,
  onError?: (error: string) => void,
): { close: () => void } {
  const source = new EventSource('/api/skills/compile/stream')

  const addHandler = (type: CompilationEvent['event']) => {
    source.addEventListener(type, (e: MessageEvent) => {
      try {
        onEvent(JSON.parse(e.data) as CompilationEvent)
      } catch {
        // ignore malformed messages
      }
    })
  }

  addHandler('skill_compiled')
  addHandler('compilation_progress')
  addHandler('compilation_done')
  addHandler('compilation_error')

  source.onerror = () => {
    // EventSource auto-reconnects on network errors, but not on HTTP 4xx/5xx.
    // If the stream is unreachable (404, 500), the connection dies silently.
    // Surface this to the UI so the user knows something is wrong.
    if (source.readyState === EventSource.CLOSED) {
      onError?.('Compilation stream disconnected. The server may be unavailable.')
    }
  }

  return {
    close() {
      source.close()
    },
  }
}
```

### Phase 5: Store Updates

**File**: `dashboard-ui/src/stores/skills.ts`

Add a `patchSkill` action that triggers Vue reactivity cleanly by replacing
the array reference:

```typescript
import type { SkillCompilationSummary } from '@/types/dashboard'
// ... existing imports ...

export function useSkillsStore() {
  // ... existing store creation ...

  function patchSkill(name: string, data: Partial<SkillCompilationSummary>) {
    const current = store.data.value ?? []
    const idx = current.findIndex(s => s.name === name)
    const updated = [...current]
    if (idx >= 0) {
      updated[idx] = { ...updated[idx], ...data } as SkillCompilationSummary
    } else {
      // First compilation for this skill — push new entry.
      // Must have required fields; caller guarantees skill_compiled event carries them.
      updated.push(data as SkillCompilationSummary)
    }
    store.data.value = updated  // triggers ref reactivity via array replacement
  }

  // ... expose patchSkill on the returned store ...
}
```

Add `pause`/`resume` to `useCompilationProgressStore` so polling can be
suspended while SSE is active:

```typescript
export const useCompilationProgressStore = () => {
  // ... existing polling setup ...

  let _paused = false

  function pause() { _paused = true }
  function resume() { _paused = false }

  // In the polling interval callback:
  //   if (_paused) return

  return { ...store, pause, resume }
}
```

### Phase 6: View Updates

**File**: `dashboard-ui/src/views/SkillsView.vue`

Replace the `<script setup>` with reactive SSE-driven logic:

1. **Remove** the `watch` on `progress.data?.running` (line ~113 in current code).
2. **Remove** the `setInterval`/`setTimeout` polling in `compileOne()`.
3. **Add** a `startCompilationStream()` function called from both `triggerCompile()`
   and `compileOne()`:

```typescript
import { createCompilationStream } from '@/api/compilation-sse'
import type { CompilationEvent } from '@/types/dashboard'

let streamClose: (() => void) | null = null

function startCompilationStream() {
  // Pause polling while SSE is active
  progress.pause()

  streamClose = createCompilationStream(
    (event: CompilationEvent) => {
      switch (event.event) {
        case 'skill_compiled': {
          // Patch the individual skill card in-place
          const { event: _, ...skillData } = event
          store.patchSkill(event.skill_name, skillData)
          break
        }
        case 'compilation_progress':
          // Update reactive progress counts directly
          progressCounts.value = {
            total: event.total,
            completed: event.completed,
            errors: event.errors,
            running: event.running,
          }
          break
        case 'compilation_done':
          compiling.value = false
          compilingSkill.value = ''
          // Final reconciliation — catches any events missed during reconnect
          store.fetch()
          streamClose?.()
          streamClose = null
          progress.resume()
          break
        case 'compilation_error':
          compileError.value = event.detail
          compiling.value = false
          compilingSkill.value = ''
          streamClose?.()
          streamClose = null
          progress.resume()
          break
      }
    },
    (error: string) => {
      compileError.value = error
      compiling.value = false
      progress.resume()
    },
  )
}

function stopCompilationStream() {
  streamClose?.()
  streamClose = null
  progress.resume()
}
```

4. **Update `triggerCompile()`** to call `startCompilationStream()` after the
   POST succeeds (removing the watch-based auto-refetch):

```typescript
async function triggerCompile() {
  compileError.value = ''
  compiling.value = true
  try {
    const res = await postCompileSkills()
    if (res.status === 'started') {
      startCompilationStream()
    } else if (res.status === 'already_running') {
      // Compilation is already running — join the existing stream
      compiling.value = true
      startCompilationStream()
    } else if (res.status === 'error') {
      compileError.value = res.detail ?? 'Unknown error'
      compiling.value = false
    } else if (res.status === 'no_skills_found') {
      compileError.value = 'No SKILL.md files found.'
      compiling.value = false
    }
  } catch (e: any) {
    compileError.value = e?.message ?? 'Request failed'
    compiling.value = false
  }
}
```

5. **Update `compileOne()`** to use the stream instead of polling:

```typescript
async function compileOne(name: string) {
  compilingSkill.value = name
  try {
    const res = await postCompileSkill(name)
    if (res.status === 'started') {
      startCompilationStream()
    } else {
      compileError.value = res.detail ?? res.status
      compilingSkill.value = ''
    }
  } catch (e: any) {
    compileError.value = e?.message ?? 'Request failed'
    compilingSkill.value = ''
  }
}
```

6. **Add cleanup** in `onUnmounted`:

```typescript
import { onUnmounted } from 'vue'

onUnmounted(() => {
  stopCompilationStream()
})
```

7. **Replace `const pct = computed(...)`** to use the reactive `progressCounts`
   ref instead of `progress.data`:

```typescript
const progressCounts = ref({ total: 0, completed: 0, errors: 0, running: false })

const pct = computed(() => {
  if (!progressCounts.value.total) return 0
  return Math.round((progressCounts.value.completed / progressCounts.value.total) * 100)
})
```

8. **Update the progress bar template** to bind to `progressCounts` instead of
   `progress.data`:

```html
<span class="text-xs text-[var(--text-muted)] font-mono">
  {{ progressCounts.completed }} / {{ progressCounts.total }}
  <span v-if="progressCounts.errors > 0" class="text-red-400 ml-2">
    &middot; {{ progressCounts.errors }} errors
  </span>
</span>
<!-- ... -->
:class="progressCounts.errors > 0 ? 'bg-amber-400' : 'bg-[var(--accent-blue)]'"
```

### Phase 7: Cleanup

1. **Keep** `GET /api/skills/progress` as a fallback for clients that don't use SSE (TUI, CLI).
2. **Keep** `useCompilationProgressStore` but its polling is paused during SSE.
3. **Keep** `useSkillsStore` polling at 15s as a background consistency check (doesn't hurt).
4. The `_rejected_bundle` function in `skill_compiler.py` needs `compiled_at` to be settable
   (currently it's `0.0` by default in `SkillBundle`). Acceptable — the event builder
   will produce epoch 1970 for rejected bundles, which the UI can handle.

## What This Replaces

| Before | After |
|--------|-------|
| `GET /api/skills/progress` poll every 5s | `compilation_progress` SSE event pushed on every skill |
| `GET /api/skills` poll every 15s + full refetch on done | `skill_compiled` SSE event patches individual cards; `compilation_done` triggers one reconciliation `fetch()` |
| `setInterval(fetch, 2000)` per single-skill compile | `skill_compiled` SSE event pushes result; `compilation_done` closes stream |
| `watch(progress.data?.running)` triggers full refetch | No watch — `compilation_done` event drives state |

## Edge Cases & Resilience

- **Multiple browser tabs**: Fan-out via `_clients: set[asyncio.Queue]`. Each tab gets
  its own queue. Dead clients (full queue) are pruned on publish.
- **Late-joining client**: SSE endpoint emits a `compilation_progress` snapshot on
  connect if compilation is running, so the UI immediately shows the progress bar.
- **Reconnection during compilation**: `EventSource` auto-reconnects on network
  errors. Missed events are handled by the final `store.fetch()` reconciliation on
  `compilation_done`. If the stream gets an HTTP 4xx/5xx, `onerror` surfaces it to
  the UI via `onError` callback.
- **Daemon thread crash**: `try/finally` in `_compile_all` guarantees
  `compilation_done` always fires. UI never gets stuck in "compiling" state.
- **Concurrent POST requests**: TOCTOU fixed by setting `running=True` before
  spawning the thread. Single-skill compile checks `running` and refuses if a batch
  compile is in progress.
- **Queue backpressure**: Bounded queues (`maxsize=50`). A slow client that falls
  behind gets pruned (its events are dropped). The client's `EventSource` will
  reconnect and get a snapshot.
- **Empty compilation**: `compilation_done` emitted immediately with `total: 0`.

## Non-Goals

- WebSocket upgrade — SSE is sufficient and already in the stack.
- Persisting compilation events to the DB — this is a UI streaming concern, not a durable event.
- Streaming to the TUI — the Textual TUI can consume the same SSE endpoint later, but this spec scopes to the dashboard.
- Real-time streaming of the LLM compilation call itself (token-by-token) — that's a separate feature.
