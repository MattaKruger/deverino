# Event-Sourced Context Map Design

**Date:** 2026-05-20
**Status:** draft
**Author:** Matthijs Kruger
**References:**

- PEEK: Context Map as an Orientation Cache for Long-Context LLM Agents (Gu, Zhang, Khattab, Madden — MIT/Stanford, May 2026)
- `docs/papers/2605.19932.pdf`
- `docs/superpowers/specs/2026-05-18-event-driven-agents-design.md`

---

## Problem

When an LLM agent repeatedly queries the same external context (a codebase, a corpus, a knowledge base), it spends significant effort on **orientation** every time: discovering what the context contains, how it's organized, what entities exist, what formats are used. This orientation knowledge is _transferable_ across queries, but no current mechanism preserves it between sessions.

The PEEK paper proposes a **context map** — a small, fixed-budget artifact that lives in the agent's system prompt, acting as an agent-side cache for orientation knowledge. PEEK updates the map synchronously from execution trajectories via a three-module pipeline: Distiller → Cartographer → Evictor.

**The constraint:** PEEK's Distiller runs inline after every query, analyzing the full execution trajectory. This means:

1. Every query pays an LLM call for the Distiller, regardless of whether new orientation knowledge was discovered.
2. The trajectory is ephemeral — once the map is updated, the trajectory is discarded.
3. The map update blocks the agent loop — no query can begin until the previous map update completes.

**This document explores an alternative:** running the Distiller as an **asynchronous materializer over an event store**, decoupling the agent loop from map maintenance while preserving the PEEK abstraction.

---

## The Key Insight

PEEK's pipeline already maps onto event-sourcing primitives:

| PEEK component       | Event-sourcing analog                              |
| -------------------- | -------------------------------------------------- |
| Execution trajectory | Event stream (append-only log)                     |
| Distiller            | Materializer (LLM call over unprocessed events)    |
| Cartographer         | Projection rule (structured edits from LLM output) |
| Evictor              | Projection rule (deterministic budget enforcement) |
| Context map          | Read model / projection (fresh for each query)     |

The Distiller is literally a **materializer function**: it takes raw data (trajectory/events) and produces a structured view (diagnosis + cache candidates). The only differences are:

- **Input format:** events vs. full trajectory text
- **Cadence:** async vs. inline
- **Granularity:** selective (only when signal exists) vs. every query

Neither difference invalidates the PEEK insight. The context map structure, the Distiller's diagnosis/tags/candidates output, the Cartographer's edit operations, and the Evictor's priority budget are all preserved.

---

## Architecture

```
┌──────────────────────────────┐
│        Agent Loop            │
│                              │
│  1. Load context map         │
│     from blackboard          │
│  2. Run query with map       │
│     in system prompt         │
│  3. Emit structured events   │
│     (cheap, synchronous)     │
│  4. Return result            │
└──────────┬───────────────────┘
           │ append_event (tool call)
           ▼
┌──────────────────────────────┐
│      Event Store             │
│  (blackboard event log,      │
│   append-only, typed)        │
└──────────┬───────────────────┘
           │ async polling
           ▼
┌──────────────────────────────┐
│  MaterializerRunner          │
│                              │
│  1. Fetch unprocessed events │
│  2. Run Distiller (LLM)      │
│  3. Run Cartographer (LLM)   │
│  4. Run Evictor              │
│  5. Write map + mark events  │
│     processed (atomic)       │
└──────────┬───────────────────┘
           │ writes
           ▼
┌──────────────────────────────┐
│    Context Map (persistent)  │
│  keyed by project + corpus   │
└──────────┬───────────────────┘
           │ loaded at session start
           ▼
┌──────────────────────────────┐
│     System Prompt Builder    │
│  (injects map into prompt)   │
└──────────────────────────────┘
```

### Flow

1. **Agent runs a query.** The current context map (if any) is loaded from the blackboard and injected into the system prompt alongside the external context.
2. **Agent emits events.** After each tool call, retrieval, or observation, the agent (or a post-execution hook) calls `append_event` to write typed events to the event store. This is cheap — a single INSERT, ~1ms.
3. **MaterializerRunner polls.** A dedicated background runner polls for unprocessed events. When found, it feeds them to the Distiller LLM call. (The `GoalRunner` is reserved for the autonomous ReAct loop — materializer logic lives in a separate `MaterializerRunner`.)
4. **Distiller produces diagnosis + tags + raw observations.** The LLM receives the batch of unprocessed events (bounded to a max input token budget) plus the current context map. It identifies what orientation knowledge was discovered but does not produce structured edits — that is the Cartographer's job.
5. **Cartographer applies edits.** In a second LLM pass, the Cartographer receives the Distiller's diagnosis and raw observations and translates them into structured edit operations (ADD, DELETE, REPLACE) against the map, assigning each to a section with a priority score. Separating this from the Distiller prevents the Distiller from conflating discovery with structural decisions.
6. **Evictor enforces budget.** If the updated map exceeds the token budget (default: 1024 tokens), items are evicted in ascending priority order: Parsing Schema → Reusable Results → Domain Constants → Context Roadmap / Context Understanding (protected last).
7. **Map is written atomically.** The updated map and the processed-event markers are committed in a single SQLite transaction. If the Distiller or Cartographer LLM call fails, neither the map nor the event markers change — the next poll retries the same batch.
8. **Next query loads fresh map.** The agent loop loads the updated map on the next query. Staleness is acceptable — the map is a cache, not a source of truth. The only concurrent-write risk is two `MaterializerRunner` instances processing the same corpus simultaneously; a corpus-level advisory lock (SQLite `BEGIN EXCLUSIVE` scoped to the corpus key) prevents double-processing.

---

## corpus_key Assignment

Every event and map entry is scoped to a `corpus_key`, a stable project-level identifier for an external context. `corpus_key` is not session-scoped — it must be consistent across sessions so the map accumulates knowledge over time.

**How `corpus_key` is determined:**

- Tools that interact with an external context declare a `corpus_key` in their registration metadata (e.g., `"corpus_key": "codebase"`, `"corpus_key": "wiki"`).
- `append_event` receives the `corpus_key` from the calling tool, not from the agent. The agent does not need to know about corpus boundaries.
- For multi-corpus sessions (an agent switching between a codebase and a knowledge base), each tool carries its own `corpus_key`. Maps are maintained independently per corpus.
- `corpus_key` is stored as `{project_id}:{corpus_name}` (e.g., `"deverino:codebase"`) to ensure cross-session persistence is project-scoped rather than user-scoped or session-scoped.

`project_id` comes from `harness.yaml` (`project.id`). If absent, a hash of the working directory path is used as a stable fallback. This key format is established in Phase 1 to avoid a schema migration later.

---

## Event Schema

Events are the core abstraction. They must be rich enough for the Distiller to extract transferable knowledge, but cheap enough to emit on every tool call without meaningful overhead.

Events record **observations only** — no assessments, no computed history. Fields like confidence scores or recurrence counts belong in the materializer layer, where they are derived from the event stream, not authored by the emitting agent.

```python
# Base
class ContextMapEvent(BaseModel):
    event_id: str  # UUID
    timestamp: datetime
    session_id: str
    corpus_key: str  # "{project_id}:{corpus_name}", stable across sessions
    event_type: str

# --- Ingestion events ---
class CorpusIngested(ContextMapEvent):
    event_type: Literal["corpus_ingested"]
    corpus_name: str
    document_count: int
    total_tokens: int
    schema_hint: str | None  # e.g., "CSV with 5 columns", "Markdown docs"

# --- Retrieval events ---
class DocumentRetrieved(ContextMapEvent):
    event_type: Literal["document_retrieved"]
    query: str
    retrieved_doc_ids: list[str]
    retrieved_doc_titles: list[str]
    retrieval_strategy: str  # "semantic", "keyword", "hybrid"

# --- Entity discovery events ---
class EntityReferenced(ContextMapEvent):
    event_type: Literal["entity_referenced"]
    entity_name: str
    entity_type: str  # "concept", "constant", "schema", "person", "api"
    context: str  # brief snippet showing usage
    # Recurrence count is NOT stored here — it is derived by the materializer
    # by querying the event store, not denormalized into each event.

# --- Schema discovery events ---
class SchemaDiscovered(ContextMapEvent):
    event_type: Literal["schema_discovered"]
    schema_description: str
    example: str
    # Confidence is an assessment, not an observation. The Distiller assigns
    # confidence to its output; the raw event records only what was observed.

# --- Error / boundary events ---
class SearchFailed(ContextMapEvent):
    event_type: Literal["search_failed"]
    attempted_query: str
    strategy: str
    error: str

class FactDisputed(ContextMapEvent):
    event_type: Literal["fact_disputed"]
    previous_claim: str
    corrected_claim: str
    source_doc_id: str

# --- Derivation events (emitted by the MaterializerRunner itself) ---
class ContextualInsightDiscovered(ContextMapEvent):
    event_type: Literal["contextual_insight_discovered"]
    insight: str
    supporting_events: list[str]  # event IDs
    map_section: str  # which section this feeds into

class MapEntryPromoted(ContextMapEvent):
    event_type: Literal["map_entry_promoted"]
    entry_key: str
    from_section: str
    to_section: str  # e.g., from ReusableResults → DomainConstants

class MapEntryEvicted(ContextMapEvent):
    event_type: Literal["map_entry_evicted"]
    entry_key: str
    section: str
    reason: str
```

**Design principle:** Thin events are cheap to emit and universally applicable. Derivation events are produced by the materializer, not the agent — they document the map's evolution for debugging and replay.

---

## Distiller → Cartographer Pipeline

The Distiller and Cartographer are two sequential LLM passes. Keeping them separate prevents the Distiller from conflating observation with structural decisions about the map.

### Distiller prompt

The Distiller reads events and produces qualitative analysis. It does **not** assign sections or priority scores — those are Cartographer outputs.

```
You are a Context Map Distiller. Your job is to examine a batch of interaction events
from an agent working with a recurring external context, determine what the agent learned
about the context itself (not about the task), and produce structured output.

INPUT BUDGET: You will receive at most {max_event_tokens} tokens of event data.
If events were truncated, the most recent events are included; older events were dropped.

Current context map:
{current_map_json}

Unprocessed events:
{events_json}

Produce:
1. DIAGNOSIS: A brief summary of what orientation knowledge was discovered or confirmed.
   Distinguish orientation work ("the corpus has 3 sections") from task-specific work
   ("the answer to query 7 is 42"). Only orientation knowledge matters for the map.

2. PER-ITEM TAGS: For each existing map entry, tag it as:
   - "helpful" — this entry was actively used and correct
   - "harmful" — this entry misled the agent
   - "neutral" — not relevant to this batch
   - "stale" — contradicted by new evidence

3. RAW OBSERVATIONS: A list of orientation facts discovered in this batch, in plain
   language. Do not assign sections or scores — just record what was learned.

Output format: JSON with keys "diagnosis", "tags", "observations".
```

### Cartographer prompt

The Cartographer receives the Distiller's output and produces structured edit operations.

```
You are a Context Map Cartographer. You receive an analysis of what an agent learned
about an external context and translate it into structured edits to the context map.

Distiller output:
{distiller_output_json}

Current context map:
{current_map_json}

For each observation in the Distiller output, decide:
- Whether it warrants an ADD, DELETE, or REPLACE operation on the map
- Which section it belongs to (context_roadmap, context_understanding, domain_constants,
  reusable_results, parsing_schema)
- A priority score (0.0–1.0, higher = more valuable to retain under budget pressure)
- Supporting event IDs from the Distiller's observations

Also apply tag-driven deletions: any entry tagged "harmful" or "stale" by the Distiller
should produce a DELETE operation unless overridden by new conflicting evidence.

Output format: JSON with key "edits", each edit having:
  op (ADD|DELETE|REPLACE), section, entry_key, content, priority_score, supporting_event_ids
```

---

## Harness Integration Points

### New system skill: `append_event`

```python
def execute(ctx: SkillContext) -> SkillResult:
    """Append a structured event to the event store.

    Expected ctx.args keys: event_type, corpus_key, payload (dict).
    Inserts a row into context_map_events; returns the new event_id.
    """
```

### Modified system prompt assembly

```python
# In the prompt builder, before agent run:
corpus_key = f"{config.project_id}:{corpus_name}"
context_map = database.get_context_map(corpus_key)
if context_map:
    system_prompt += f"\n\n--- Context Map ---\n{context_map}\n---"
```

### New skill: `context-map-materializer`

A skill that runs the full Distiller → Cartographer → Evictor pipeline for a given `corpus_key`. It can be invoked:

- By `MaterializerRunner` on a poll loop
- Manually via `/skill context-map-materializer corpus_key=deverino:codebase`

### MaterializerRunner

A lightweight background runner (separate from `GoalRunner`) that polls for unprocessed events and invokes the materializer skill. Unlike `GoalRunner`, it has no ReAct loop, stuck detection, or context compression — it is a simple poll → invoke → sleep cycle.

```python
class MaterializerRunner:
    def __init__(self, db: BlackboardDatabase, skill_runner: SkillRunner, poll_interval: float = 30.0):
        ...

    async def run_forever(self) -> None:
        while True:
            pending = self._db.get_pending_corpus_keys()
            for corpus_key in pending:
                await self._materialize(corpus_key)
            await asyncio.sleep(self._poll_interval)
```

A corpus-level advisory lock (SQLite `BEGIN EXCLUSIVE` scoped to the corpus key) prevents two `MaterializerRunner` instances from double-processing the same corpus if multiple processes share the blackboard.

### New pipeline (optional, future)

The pipeline YAML below references skills (`blackboard_query`, `jq_filter`, `blackboard_execute`) that do not yet exist in the harness. They are prerequisites of Phase 3 and must be built before this pipeline can run.

```yaml
id: context-map-materializer
trigger: interval 30s
nodes:
  - id: fetch_events
    skill: blackboard_query
    args:
      query: >
        SELECT * FROM context_map_events
        WHERE processed = 0 AND corpus_key IS NOT NULL
        ORDER BY timestamp
        LIMIT 50

  - id: group_by_corpus
    skill: jq_filter
    args: { filter: "group_by(.corpus_key)", input_from: fetch_events }

  - id: materialize
    skill: context-map-materializer
    args: { events: group_by_corpus, input_from: group_by_corpus }
    foreach: true

  - id: mark_processed
    skill: blackboard_execute
    args:
      query: >
        UPDATE context_map_events SET processed = 1
        WHERE event_id IN (SELECT event_id FROM fetch_events)
```

### Blackboard schema

The event store extends the existing `BlackboardDatabase` with two new tables. All writes to `context_map` and `context_map_events.processed` are performed in a single transaction to ensure atomicity — if the Distiller or Cartographer LLM call fails, neither the map nor the event markers change, and the next poll retries the same batch.

```sql
-- Append-only event log
CREATE TABLE context_map_events (
    event_id     TEXT PRIMARY KEY,       -- UUID
    corpus_key   TEXT NOT NULL,          -- "{project_id}:{corpus_name}"
    session_id   TEXT NOT NULL,
    event_type   TEXT NOT NULL,
    payload      TEXT NOT NULL,          -- JSON
    timestamp    TEXT NOT NULL,          -- ISO-8601
    processed    INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX idx_events_corpus_unprocessed
    ON context_map_events (corpus_key, processed, timestamp);

-- Current map per corpus (project-scoped, persists across sessions)
CREATE TABLE context_map (
    corpus_key       TEXT PRIMARY KEY,
    map_json         TEXT NOT NULL,      -- structured map JSON
    token_count      INTEGER NOT NULL,
    version          INTEGER NOT NULL DEFAULT 1,
    last_updated     TEXT NOT NULL       -- ISO-8601
);
```

---

## Design Decisions & Trade-offs

| Decision                                          | Rationale                                                                                                                                                            |
| ------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Event-based instead of trajectory-based**       | Decouples agent loop from map update. Events are cheaper to emit and easier to replay. Trade-off: some trajectory depth is lost (internal reasoning steps).          |
| **Async materialization**                         | Map may be stale by N events. Acceptable because the map is a cache, not a source of truth. PEEK's synchronous model guarantees freshness but blocks the agent loop. |
| **Two-pass Distiller → Cartographer**             | Distiller handles qualitative analysis; Cartographer handles structural decisions. Prevents conflation of observation and map editing, and keeps each prompt focused. |
| **Thin events + rich derivation events**          | Thin events are universally applicable and cheap. Derivation events are produced by the materializer, documenting map evolution for debugging.                       |
| **No assessment fields in raw events**            | Confidence scores and recurrence counts are materializer outputs, not agent observations. Keeps events as pure facts and avoids requiring agents to query history before emitting. |
| **Project-scoped corpus key from Phase 1**        | Using `{project_id}:{corpus_name}` from the start avoids a schema migration when cross-session persistence is wired up.                                              |
| **Atomic map + event-marker transaction**         | Writing the updated map and marking events processed in a single SQLite transaction ensures no partial state: either both commit or neither does.                    |
| **Dedicated MaterializerRunner (not GoalRunner)** | GoalRunner is the autonomous ReAct loop with stuck detection and context compression. The materializer is a simple poll cycle; conflating them would complicate debugging. |
| **Blackboard as event store**                     | Reuses existing infrastructure. For high-throughput scenarios, a dedicated event store (PostgreSQL, Kafka) could be swapped in later without changing the Distiller. |

### Open Questions

1. **Event granularity.** How many distinct event types are enough? Too few loses signal, too many adds complexity. Start with 6–8 types and iterate.
2. **Materializer cadence.** Poll-driven (every N seconds) or push-driven (materializer subscribes to a stream)? Poll is simpler for the harness today.
3. **Staleness tolerance.** How many queries can run with a stale map before accuracy degrades? Needs empirical evaluation.
4. **Distiller cost.** Every materializer run is two LLM calls (Distiller + Cartographer). Batch size and debounce window need tuning to avoid excessive spend. Default max input budget: 8000 tokens of event data per batch (approximately 50 thin events).
5. **Concurrent materializers.** If two `MaterializerRunner` instances share a blackboard (e.g., two CLI processes), a corpus-level `BEGIN EXCLUSIVE` transaction prevents double-processing. Verify this holds under the SQLite WAL journal mode used by the harness.

---

## Implementation Plan (Phased)

### Phase 1: Foundation

- [ ] Decide `project_id` source (`harness.yaml` field or working-directory hash fallback)
- [ ] Define event types as Pydantic models (`corpus_key` field, no assessment fields)
- [ ] Write SQL DDL for `context_map_events` and `context_map` tables; migrate `BlackboardDatabase`
- [ ] Add `append_event` skill (`ctx: SkillContext`, inserts into `context_map_events`)
- [ ] Write a manual `context-map-materializer` skill (Distiller → Cartographer → Evictor, atomic commit)

### Phase 2: Materializer Loop

- [ ] Wire `append_event` calls into existing tool post-execution hooks (emit events automatically)
- [ ] Test Distiller + Cartographer prompts against real events; tune section and priority logic
- [ ] Wire context map into system prompt assembly (`database.get_context_map(corpus_key)`)

### Phase 3: Async Background

- [ ] Implement `MaterializerRunner` (poll loop, corpus-level lock, separate from `GoalRunner`)
- [ ] Add debounce / batch-size tuning knobs to `harness.yaml`
- [ ] Build prerequisite skills for pipeline YAML: `blackboard_query`, `jq_filter`, `blackboard_execute`
- [ ] Benchmark against PEEK's reported results

### Phase 4: Observability

- [ ] Derivation events (insight, promotion, eviction) emitted by `MaterializerRunner`
- [ ] Skill or dashboard to inspect current map contents and event log
- [ ] Replay: rebuild map from scratch from event stream (validates event completeness)
