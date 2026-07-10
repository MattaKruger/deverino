---
title: Deverino Architecture Map
mapped_at: 2026-07-11
last_mapped_commit: cf99f7e
focus: architecture
---

# Architecture

## System Shape

Deverino is a Python agent harness with PostgreSQL as its durable blackboard. The
application has a shared infrastructure kernel under `harness_poc/core/`, a newer
orchestration layer under `harness_poc/v2/`, and three user-facing surfaces: Typer CLI/REPL,
Textual TUI, and FastAPI plus a Vue dashboard.

The repository calls the shared event runtime "v1" in comments and v2 documentation, but
there is no current `harness_poc/v1/` package. In this map, **core runtime** means the
historically-v1 implementation in `harness_poc/core/`; **v2 runtime** means the adapters,
engines, subscribers, and orchestrator in `harness_poc/v2/`.

```text
CLI / REPL / TUI              FastAPI / Vue dashboard
        |                              |
        v                              v
  app_factory.py                 api/*.py
        |                              |
        +---------- PostgreSQL --------+
        |
        +-- core runtime: model, skills, tools, events, state, context maps
        |
        +-- v2 runtime: ReAct subscribers OR probe/execute/gate pipeline
        |
        +-- optional Vespa retrieval and container execution
```

## Entry Points

| Surface | Entry point | Responsibility |
|---|---|---|
| Package command | `harness_poc/main.py:main` | Invokes the Typer application exported by `harness_poc/cli.py`. |
| Interactive REPL | `harness_poc/cli.py:repl` | Builds `AppState`, optionally resumes a session, then enters `harness_poc/repl.py`. |
| Textual TUI | `harness_poc/tui.py` | Rich terminal shell over the same `AppState` and REPL handlers. |
| Goal runner | `harness_poc/cli.py:goal` | Runs the iterative model/tool goal loop in `core/runtime/goal_runner.py`. |
| Workflow/pipeline CLI | `harness_poc/cli.py` sub-apps | Runs sequential YAML workflows, DAG pipelines, or v2 workflows. |
| Dashboard API | `harness_poc/api/__init__.py:create_app_from_config` | Creates FastAPI routes over the blackboard and chat runtime. |
| Dashboard UI | `dashboard-ui/src/main.ts` | Mounts Vue, Pinia, and routes from `dashboard-ui/src/router.ts`. |

`pyproject.toml` exposes `harness-poc = harness_poc.main:main`. The normal bootstrap path is
`build_app_state()` in `harness_poc/app_factory.py`.

## Bootstrap and Composition

`harness_poc/app_factory.py` is the composition root:

1. `HarnessConfig.load()` reads `harness.yaml` and resolves project paths.
2. `build_identity()` creates the SQLModel engine, `BlackboardDatabase`, `EventStore`,
   persisted session, and in-process `EventBus`.
3. `build_runtime_layer()` creates `SkillRunner`, guarded `ToolRunner`, YAML workflow and
   pipeline runners, skill catalog, and `PydanticAgentRuntime`.
4. `compose_system_prompt()` combines SOUL, project state, session state, the active corpus
   context map, optional related corpora, and the ACDL prompt order.
5. `build_long_lived()` creates the context `MaterializerRunner` and core
   `ProcessorSupervisor`.
6. `_build_v2_runtime_if_needed()` adds a v2 pipeline or ReAct runtime for those modes.

`Identity` contains stable process/session dependencies. `Runtime` contains reloadable model,
skill, tool, and workflow dependencies. `LongLived` owns background processors. `AppState`
groups all three and carries message history, streaming callbacks, mode, and active-run state.

## Capability Layers

### Model Runtime

`harness_poc/core/runtime/pydantic_runtime.py` is the model integration chokepoint. It resolves
providers, creates the PydanticAI agent, exposes skills and built-in tools, streams model output,
and supports an offline `TestModel`. `message_history.py` bounds and sanitizes history;
`token_accounting.py` normalizes usage; `reducers.py` derives session state from persisted events.

### Skills and Tools

`harness_poc/core/skills/` discovers `SKILL.md` documents in
`harness_poc/system_skills/` and `skills/`, loads their Python entrypoints, applies declared
workspace/blackboard permissions, and executes them with `SkillContext`.

`harness_poc/core/tools/` runs code-native tools registered by `harness_poc/system_tools/`.
`ToolRunner` applies path, size, type, idempotency, content, and query guards before dispatch.
Project skills declared as `type: tool` are mounted into the same tool surface but still execute
through `SkillRunner`.

### Orchestration

There are three orchestration forms:

- `core/execution/workflow_runner.py`: sequential YAML state machine in `workflows/`; each state
  runs one skill and may read/write blackboard state.
- `core/execution/pipeline_runner.py`: YAML DAG in `pipelines/`; topological waves run skill or
  agent nodes, with independent nodes executed in threads.
- `v2/workflow_orchestrator.py`: probe, sub-agent execution, deterministic test gate, and
  verified-context refresh; it can run imperatively or through bus subscribers.

`core/acdl/` parses and executes the ACDL prompt/control specification. The checked-in
`deverino_react.acdl` currently controls system-prompt composition.

## Runtime Generations

### Core Runtime (Historically v1)

The core event loop uses `core/processors/llm_worker.py`, `tool_worker.py`, and
`circuit_breaker.py`. `ProcessorSupervisor` starts these workers against one session-scoped
`EventBus`. Native chat bypasses this subscriber loop and calls `PydanticAgentRuntime` directly,
while still publishing usage/input events and persisting message history.

The core runtime owns the canonical application composition, database facade, event store,
skills, tools, prompt assembly, and corpus-key context projection. V2 depends on these pieces.

### V2 ReAct Mode

`harness_poc/v2/wiring.py:build_v2_runtime(..., mode="react")` mounts v2 `LlmWorker`,
`ToolWorker`, `CircuitBreaker`, and `GoalEvaluator` subscribers on the existing core `EventBus`.
Input, skill-request, skill-completion, text, budget, and goal events circulate through the same
persist-before-dispatch path as core events.

### V2 Pipeline Mode

Pipeline mode composes `ContextEngine`, `ExecutionEngine`, and `WorkflowOrchestrator`.
`ContextEngine` combines persona, pedagogy, verified state, and a context materializer.
`ExecutionEngine` owns sub-agent dispatch/background tracking and the deterministic test gate.
`WorkflowOrchestrator` sequences fail-fast probe, spec execution, and gate, then refreshes the v2
materialized snapshot only after successful verification.

V2 is an integration layer, not an independent platform: it reuses the core database, event bus,
skill runner, model builder, context renderer, personas, and system prompts.

## Event and Context Flows

### Session Event Stream

```text
typed BaseEvent (Pydantic)
  -> EventBus.publish()
  -> EventStore.persist()
  -> state_events row (scope=session, scope_id=session_id)
  -> synchronous handlers + bounded async subscriber queues
  -> reducers, workers, observability queries, dashboard
```

`core/events/events.py` defines the closed `BaseEvent` class set and `EVENT_REGISTRY` used for
deserialization. `EventBus` is in-process pub/sub; PostgreSQL is the durable log, not the delivery
mechanism. Publishing persists before dispatch. Slow async subscribers may lose live queue items
when their 500-event queue fills, but the durable event row remains.

### Corpus Context Projection

```text
typed ContextMapEvent
  -> BlackboardDatabase.append_context_map_event()
  -> context_map_events row, processed=0, partitioned by corpus_key
  -> MaterializerRunner polls pending corpus keys
  -> context-map-materializer skill
  -> optional CopT semantic redundancy gates
  -> LLM Distiller: event batch -> DistillerEntry observations
  -> deterministic Cartographer: observations + current map + policy -> MapEntry list
  -> atomic map write + processed flags
  -> context_map projection + context_map_cycles
  -> render_context_map() -> system prompt
```

`core/context_map/schema.py` defines distilled observations and materialized entries.
`distiller.py` is the model-dependent interpretation stage. `cartographer.py` is deterministic
given its inputs, configuration, cycle, and supplied clock. `sections.py`, `config.py`, and
`render.py` hold classification, policy, and presentation.

The current materializer persists raw context events and the final projection, but distilled
observations are transient. `write_map_and_mark_processed()` commits the projection and consumed
event flags in one database transaction. It increments map version, but does not compare an
expected version for optimistic concurrency.

### V2 Context Snapshot

V2 also owns `materialized_context_maps_v2`, keyed by `project_id`. It stores active persona,
pedagogy snapshot, verified state, and last event ID. This is separate from the corpus-keyed
`context_map` projection. When `ContextEngine` has an `EventBus`, its probe/context events go only
through `state_events`; its direct-database fallback wraps them as `ContextEventBridge` records in
`context_map_events`.

### Durable State and Session Continuity

Project and session state are materialized records (`project_state`, `session_state`) with proposal
and approval flow in `state_proposals`. `state_events` is also reduced into `session_snapshots` by
`core/runtime/reducers.py`. PydanticAI message batches live in `session_messages` and are restored
by `build_app_state()` when a session is resumed. `shared_memory` stores arbitrary keyed outputs.

## Storage Ownership

`harness_poc/core/storage/models.py` owns SQLModel table definitions. The primary tables are:

| Concern | Tables |
|---|---|
| Sessions/history | `sessions`, `session_messages`, `session_snapshots`, `shared_memory` |
| State | `project_state`, `session_state`, `state_proposals`, `state_events` |
| Context backbone | `context_map_events`, `context_map`, `context_map_cycles`, `context_map_embeddings` |
| V2 verified snapshot | `materialized_context_maps_v2` |
| Retrieval catalog | `document_sources`, `document_chunks` |

`BlackboardDatabase` in `core/storage/database.py` is the broad application facade. SQLModel uses
PostgreSQL JSONB in production and JSON for SQLite tests. `BlackboardAccessProxy` enforces declared
skill permissions by classifying mutating database methods.

## Retrieval and External Execution

`core/retrieval/` converts and chunks documents, embeds them, indexes/queryies Vespa, and records
source/chunk metadata in PostgreSQL. `vespa/document_retrieval/` owns the Vespa application schema.
Startup may preload the embedding model and auto-index configured paths when retrieval is enabled.

Container tools in `harness_poc/system_tools/` provide spawn, exec, and destroy operations through
Docker or Podman. YAML workflows can declare a container lifecycle. The v2 probe instead uses a
temporary local directory and subprocess; the deterministic gate runs the configured test command
against a workspace.

## API and UI

`harness_poc/api/routes.py` is predominantly a read/observability API over SQL queries in
`core/observability/dashboard.py`, plus skill-compilation commands and SSE progress/event streams.
`harness_poc/api/chat.py` exposes session CRUD and AG-UI SSE chat backed by per-session
`PydanticAgentRuntime` objects cached on FastAPI application state.

`dashboard-ui/` is a separate Vue 3 application. Views use Pinia polling stores and
`src/api/endpoints.ts`; chat uses the AG-UI/SSE endpoint. The API does not serve the built frontend:
Vite is used in development and `dashboard-ui/dist/` must be served separately in production.

## Architectural Dependency Direction

The practical dependency direction is:

```text
surfaces (cli/repl/tui/api)
  -> app_factory and v2 wiring
  -> core runtime/execution/skills/tools/context/retrieval
  -> events and storage
  -> PostgreSQL / Vespa / model providers / container runtime
```

Exceptions are explicit composition-time imports to avoid cycles, plus v2 adapters that reach into
existing core implementations. Domain-neutral pieces with the cleanest extraction boundaries are
`core/events`, `core/context_map/schema.py`, the deterministic cartographer, rendering, and the
transactional context-map persistence methods. The current distiller, materializer skill,
`BlackboardDatabase`, and polling runner are still harness/config/model coupled.
