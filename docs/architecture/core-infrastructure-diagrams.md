# Deverino Harness — Core Infrastructure Diagrams

A multi-view architectural reference for `harness_poc/core/` and the `v2` orchestration layer.
All diagrams are Mermaid and render inline in Zed. A standalone presentable version lives in
`docs/architecture/diagrams.html`.

> Diagram legend: solid arrows = runtime call / data flow; dashed arrows = async event publish
> or lazy/TYPE_CHECKING import; cylinder = datastore; box with double border = external system.

---

## 1. System Context (L1)

The harness is a Python 3.14 LLM-agent harness backed by a PostgreSQL "blackboard". External
dependencies are a Vespa search index, LLM providers, the project filesystem (skills/prompts),
and optional Logfire telemetry.

```mermaid
flowchart TD
    User([User])

    subgraph Harness["Deverino Harness (harness_poc)"]
        Entry["Entry / UI<br/>main, cli, repl, tui, app_factory"]
        Core["core/ runtime + v2 orchestration"]
    end

    PG[(PostgreSQL Blackboard<br/>+ pgvector)]
    Vespa[(Vespa Search Index)]
    LLM["LLM Providers<br/>Anthropic / OpenAI / DeepSeek / GLM"]
    FS[("Project Filesystem<br/>skills, system_skills, personas, docs")]
    LF["Logfire (optional cloud)"]

    User --> Entry
    Entry --> Core
    Core --> PG
    Core --> Vespa
    Core --> LLM
    Core --> FS
    Core -.-> LF
```

---

## 2. Layered Architecture (L2)

`core/` decomposes into six layers. Dependency direction is generally downward: the entry/UI
layer drives orchestration, which drives the runtime, which uses capabilities and intelligence,
all persisted through the state/events layer. `config`, `permissions`, `logging`, and `observe`
are cross-cutting.

```mermaid
flowchart TD
    subgraph L1["Entry / UI Layer"]
        main["main.py"]
        cli["cli.py (Typer)"]
        repl["repl.py / tui.py"]
        appfac["app_factory.py<br/>build_app_state"]
    end

    subgraph L2["Orchestration Layer"]
        v2orch["v2: WorkflowOrchestrator"]
        v2ctx["v2: ContextEngine"]
        v2exec["v2: ExecutionEngine"]
        v2wire["v2: wiring (composition root)"]
        pipe["execution: PipelineRunner"]
        wf["execution: WorkflowRunner"]
        mat["execution: MaterializerRunner"]
    end

    subgraph L3["Runtime Layer"]
        goal["runtime: GoalRunner<br/>(structured-decision loop)"]
        pyrt["runtime: PydanticAgentRuntime<br/>(native tool-calling loop)"]
        sup["processors: ProcessorSupervisor"]
        lwork["processors: llm_worker"]
        twork["processors: tool_worker"]
        cb["processors: circuit_breaker"]
    end

    subgraph L4["Capabilities Layer"]
        skills["skills: catalog, compiler, runner"]
        tools["tools: runner, guards, context"]
        acdl["acdl: parser, ast, executor"]
    end

    subgraph L5["Intelligence Layer"]
        cmap["context_map: distiller, cartographer"]
        retr["retrieval: Vespa RAG"]
        ahe["ahe: telemetry, diagnose, propose"]
        eval["eval: judge, runner, refine"]
    end

    subgraph L6["State / Events Layer"]
        stor["storage: BlackboardDatabase, proxy, state"]
        ev["events: EventBus, EventStore"]
        obs["observability: dashboard, logfire"]
        observe["observe: trace, timing, log_tap"]
    end

    subgraph XC["Cross-cutting"]
        cfg["config.py"]
        perm["permissions.py"]
        logg["logging.py"]
    end

    main --> cli
    main --> repl
    cli --> appfac
    repl --> appfac
    appfac --> v2wire
    appfac --> L3
    v2wire --> v2orch
    v2orch --> v2ctx
    v2orch --> v2exec
    appfac --> pipe
    appfac --> wf
    appfac --> mat

    L2 --> L3
    L3 --> L4
    L3 --> L5
    L4 --> L6
    L5 --> L6
    L3 --> L6

    L6 -.-> observe
    stor --> ev
    ev --> obs
    cmap -.-> retr

    XC -.-> L2
    XC -.-> L3
    XC -.-> L4
```

---

## 3. Subsystem Dependency Graph

Concrete import-level dependencies between `core/*` subsystems and `v2`. The capabilities layer
(skills/tools/acdl) is a *leaf-ish* dependency target: runtime imports it, but it imports almost
nothing back. `eval` is the most decoupled; `ahe` is the most coupled.

```mermaid
flowchart TD
    appfac["app_factory"]
    v2["v2 (orchestrator/engines/wiring)"]

    runtime["runtime<br/>(goal_runner, pydantic_runtime)"]
    proc["processors"]
    execn["execution<br/>(pipeline/workflow/materializer)"]

    skills["skills"]
    tools["tools"]
    acdl["acdl"]

    cmap["context_map"]
    retr["retrieval"]
    ahe["ahe"]
    eval["eval"]

    storage["storage<br/>(blackboard)"]
    events["events<br/>(bus/store)"]
    observ["observability"]
    observe["observe"]

    config["config"]
    perm["permissions"]

    appfac --> v2
    appfac --> runtime
    appfac --> execn
    appfac --> skills
    appfac --> tools

    v2 --> events
    v2 --> cmap
    v2 --> storage
    v2 --> runtime
    v2 --> skills

    runtime --> events
    runtime --> skills
    runtime --> storage
    runtime --> observe
    runtime --> eval

    proc --> events
    proc --> skills
    proc --> storage

    execn --> skills
    execn --> events
    execn --> runtime

    skills --> storage
    skills --> perm
    skills --> observe
    tools --> skills
    tools --> perm
    acdl --> acdl

    cmap --> events
    cmap --> storage
    cmap --> config
    retr --> storage
    retr --> config
    ahe --> storage
    ahe --> cmap
    ahe --> skills
    eval --> eval

    storage --> observe
    storage --> cmap
    events --> storage
    events --> observe
    observ --> events
    observ --> cmap
    config --> cmap
```

---

## 4. Blackboard Data Model (ER)

All tables are SQLModel. JSON columns become JSONB on PostgreSQL. Migrations are lazy
(`ALTER TABLE` / `create missing` in `BlackboardDatabase.create_tables()`), not Alembic.
`context_map_embeddings` (pgvector, 384-dim) is Postgres-only and created via raw SQL.

```mermaid
erDiagram
    sessions ||--o{ shared_memory : "session_id"
    sessions ||--|| session_state : "session_id"
    sessions ||--o{ state_events : "scope_id"
    sessions ||--|| session_snapshots : "session_id"
    sessions ||--o{ session_messages : "session_id"
    sessions ||--o{ state_proposals : "session_id"
    project_state ||--o{ state_proposals : "merged into"
    document_sources ||--o{ document_chunks : "source_id"
    context_map_cycles ||--|| context_map : "corpus_key"
    context_map_events }o--|| context_map : "corpus_key"
    context_map ||--o{ context_map_embeddings : "corpus_key (pgvector)"

    sessions {
        string session_id PK
        string global_objective
        string status
        datetime created_at
        string active_corpus_key
    }
    shared_memory {
        int id PK
        string session_id FK
        string memory_key
        text data_payload
        datetime created_at
    }
    project_state {
        string project_id PK
        json state_payload
        int version
        datetime updated_at
    }
    session_state {
        string session_id PK
        json state_payload
        int version
        bool dirty
        datetime updated_at
    }
    state_proposals {
        string proposal_id PK
        string session_id FK
        string status
        json proposal_payload
        datetime created_at
        datetime resolved_at
    }
    state_events {
        int id PK
        string scope
        string scope_id
        string event_type
        json payload
        datetime created_at
    }
    context_map_cycles {
        string corpus_key PK
        int cycle_n
        datetime updated_at
    }
    context_map {
        string corpus_key PK
        text map_json
        int token_count
        int version
        datetime last_updated
        text freeze_until
    }
    context_map_events {
        string event_id PK
        string corpus_key
        string session_id
        string event_type
        text payload
        datetime timestamp
        int processed
    }
    session_snapshots {
        string session_id PK
        int last_offset
        json state_payload
        datetime updated_at
    }
    session_messages {
        string session_id PK
        int ordinal PK
        json messages_blob
        datetime created_at
    }
    document_sources {
        string source_id PK
        string uri
        string title
        string kind
        string content_hash
        string status
        int chunk_count
        datetime indexed_at
    }
    document_chunks {
        string chunk_id PK
        string source_id FK
        int chunk_index
        string content_hash
        string vespa_id
        datetime indexed_at
    }
    materialized_context_maps_v2 {
        string project_id PK
        string active_persona
        json pedagogy_snapshot
        json verified_state
        int last_event_id
        datetime updated_at
    }
```

---

## 5. Event System

A single in-process `EventBus` sits over an `EventStore` that persists every event as a row in
`state_events` (the same table that audits direct blackboard mutations). There are two event
*families*: the `BaseEvent` registry (26 agent/skill/LLM/pipeline types) and the
`ContextMapEvent` family (16 materializer types, keyed by string `event_type`).

```mermaid
flowchart TD
    pub["Publishers<br/>runtime, processors, v2, skills"]
    bus["EventBus<br/>publish / publish_async<br/>subscribe_session (async gen)"]
    store["EventStore<br/>persist -> DbStateEvent row<br/>get_recent_events (rehydrate)"]
    db[(state_events table)]

    subgraph Sync["Sync handlers"]
        logfire["logfire_subscriber<br/>(8 handlers)"]
        logobs["event_log_observer<br/>(read projection)"]
    end

    subgraph Async["Async subscribers (per session)"]
        lw["llm_worker"]
        tw["tool_worker"]
        cbr["circuit_breaker"]
        ge["goal_evaluator (v2)"]
        pr["pipeline_runner (v2)"]
    end

    pub -->|"publish(event)"| bus
    bus --> store
    store --> db
    bus -->|"put_nowait -> queue"| Async
    bus -->|"sync dispatch"| Sync
    db -.->|"SQL read"| logobs
    logobs -.->|"CLI / TUI render"| UI["event log view"]
```

Event families at a glance:

```mermaid
flowchart LR
    subgraph Base["BaseEvent family (EVENT_REGISTRY, 26)"]
        A1["Agent: AgentStarted, AgentInputAdded, GoalEvaluated, AgentTurnRecorded"]
        A2["Skill: SkillCalled, SkillRequested, SkillCompleted, SkillCancelled"]
        A3["LLM: LLMActionEmitted, LLMTextEmitted, StreamPaused"]
        A4["SubAgent: SubAgentDispatched, SubAgentCompleted"]
        A5["Pipeline v1: PipelineStarted/NodeStarted/NodeCompleted/Completed"]
        A6["Workflow v2: WorkflowStarted, ProbeCompleted, ExecutionCompleted, GateCompleted, GatePassed, GateFailed, SpecCommitted, DelegateTaskCompleted, ContextWarmed, ProbeFailed"]
    end

    subgraph CM["ContextMapEvent family (16)"]
        C1["Ingest: CorpusIngested, DocumentRetrieved, SearchFailed"]
        C2["Discover: EntityReferenced, SchemaDiscovered, FactDisputed, ContextualInsightDiscovered, BoundaryIdentified, ConstantDocumented, ResultRecorded, ArchitectureInvariantObserved"]
        C3["Map: MapEntryInserted, MapEntryEvicted, MapEntryReferenced, MapEntryPromoted (deprecated)"]
        C4["Bridge: ContextEventBridge passthrough"]
    end
```

---

## 6. The Two Agent Loops

The codebase carries **two parallel agent-loop implementations** that share the event taxonomy,
the blackboard, `SkillRunner`, and `build_model`, but are not interchangeable.

```mermaid
flowchart TD
    subgraph LoopA["Loop A — GoalRunner (structured-decision)"]
        GA["for iteration in 1..50"]
        GB["budget guards<br/>max_seconds / max_tokens / max_iterations"]
        GC["recent_events = bus.get_recent_events"]
        GD["_decide_next_action_async<br/>Agent(output_type=GoalAction, retries=2)"]
        GE{"action.tool_name?"}
        GF["_llm_text -> LLMTextEmitted"]
        GG["evaluate_goal -> GoalEvaluated<br/>(complete? -> GoalRunResult)"]
        GH["skill -> stuck check -> SkillCalled<br/>-> execute_skill -> SkillCompleted"]
        GI["optional Reflexion:<br/>JudgeEvaluator -> rerun w/ critique"]
        GA --> GB --> GC --> GD --> GE
        GE --> GF --> GA
        GE --> GG
        GE --> GH --> GA
        GA -.-> GI
    end

    subgraph LoopB["Loop B — PydanticAgentRuntime (native tool-calling)"]
        BA["agent.run_sync / agent.iter"]
        BB["model emits tool calls"]
        BC["execute_skill_as_tool<br/>semble_search budget (3/run)"]
        BD["SkillCalled/Completed via EventStore"]
        BE["max_consecutive_tool_rounds (50)"]
        BA --> BB --> BC --> BD --> BA
        BA -.-> BE
    end

    UsedA["Used by: CLI direct run,<br/>PipelineRunner 'agent' nodes"]
    UsedB["Used by: processors llm_worker,<br/>v2 LlmWorker, /mode chat"]

    UsedA -.-> LoopA
    UsedB -.-> LoopB
```

---

## 7. ReAct Agent Loop — v2 `react` mode (sequence)

Four async workers consume the session event stream and form a ReAct loop coordinated entirely
through the bus. `CircuitBreaker` is the kill switch; `GoalEvaluator` flags completion.

```mermaid
sequenceDiagram
    participant U as User / REPL
    participant Bus as EventBus
    participant LW as LlmWorker
    participant TW as ToolWorker
    participant CB as CircuitBreaker
    participant GE as GoalEvaluator
    participant RT as PydanticAgentRuntime
    participant SR as SkillRunner
    participant DB as Blackboard

    U->>Bus: publish(AgentInputAdded)
    Bus-->>LW: event
    LW->>RT: run_text(prompt)
    RT->>SR: execute_skill (tool calls)
    SR->>DB: read/write memory, state
    RT-->>LW: content + usage
    LW->>Bus: publish(LLMActionEmitted, tokens)
    alt model requests a skill
        LW->>Bus: publish(SkillRequested)
        Bus-->>TW: event
        TW->>SR: execute_skill (in thread)
        SR-->>TW: SkillResult
        TW->>Bus: publish(SkillCompleted)
        Bus-->>LW: event (loop continues)
    else final text emitted
        LW->>LW: extract [entry:id] citations
        LW->>Bus: publish(LLMTextEmitted + MapEntryReferenced)
        Bus-->>GE: event
        GE->>Bus: publish(GoalEvaluated, is_complete)
    end

    par safety net
        Bus-->>CB: every SkillCompleted / LLMActionEmitted
        alt failures > max_retries OR tokens > max_tokens
            CB->>Bus: publish(StreamPaused)
            Bus-->>LW: break loop
            Bus-->>TW: break loop
        end
    end
```

---

## 8. v2 `pipeline` mode — 3-step workflow (sequence)

Event-chained but synchronous inside `bus.publish` callbacks. `PipelineStepRunner` subscribes
to step-boundary events and delegates each step back into `WorkflowOrchestrator`. State mutation
of the materialized context map happens **only on gate pass** (only verified code enters the map).

```mermaid
sequenceDiagram
    participant Orch as WorkflowOrchestrator
    participant Bus as EventBus
    participant PR as PipelineStepRunner
    participant Ctx as ContextEngine
    participant Exec as ExecutionEngine
    participant Spawner as SubAgentSpawner
    participant DB as Blackboard

    Orch->>Bus: publish(WorkflowStarted)
    Bus-->>PR: handle_workflow_started
    PR->>Orch: run_exploration_probe(code)

    alt probe fails
        Orch->>Ctx: warm_up_context_from_failure
        Ctx->>Bus: publish(ProbeFailed, ContextWarmed)
    end
    Orch->>Bus: publish(ProbeCompleted)
    Bus-->>PR: handle_probe_completed
    PR->>Orch: run_spec_execution(tasks)

    loop per task
        Orch->>Exec: spawn_sub_agent
        Exec->>Spawner: spawn (pydantic_ai Agent.run_sync)
        Spawner-->>Exec: DelegatedTaskResult
        Exec->>DB: write_memory (blackboard)
        Exec->>Bus: publish(DelegateTaskCompleted)
    end
    Exec->>Bus: publish(SpecCommitted, ExecutionCompleted)
    Bus-->>PR: handle_execution_completed
    PR->>Orch: run_review_gate(workspace)

    Orch->>Exec: execute_deterministic_gate (uv run pytest)
    alt gate passes
        Exec->>DB: upsert_materialized_context_map
        Exec->>Bus: publish(GatePassed)
        Orch->>Ctx: materialize_context_map (refresh)
    else gate fails
        Exec->>Bus: publish(GateFailed)
    end
    Exec->>Bus: publish(GateCompleted)
```

---

## 9. Context Map Materialization Pipeline

Runs **per cycle** as the `context-map-materializer` skill (driven by the background
`MaterializerRunner`). Only one LLM step (the distiller); the cartographer is a pure, deterministic
5-stage function. Output is rendered into the system prompt every turn.

```mermaid
flowchart TD
    evts["ContextMapEvent[]<br/>(from event store, pending)"]
    curmap["current map<br/>(MapEntry[], down-sampled)"]

    subgraph Distill["run_distiller (LLM, pydantic-ai)"]
        d1["Agent(output_type=DistilledBatch)"]
        d2["bounded retry on Timeout/ValidationError"]
        d3["validate source_event_ids against events"]
        d4["safe fallback -> []"]
        d1 --> d2 --> d3 --> d4
    end

    distilled["DistillerEntry[]<br/>(typed observations, cited)"]

    subgraph Cart["deterministic_cartographer (pure, 5 stages)"]
        s0["Stage 0: explicit removals (obsolete)"]
        s1["Dedup + merge (strict superset)"]
        s2["Priority: base + recency - staleness"]
        s3["Staleness eviction"]
        s4["Budget enforcement (section + global)"]
        s0 --> s1 --> s2 --> s3 --> s4
    end

    result["CartographerResult<br/>{new_map, evictions, cycle_n}"]
    render["render_context_map<br/>(structured / json / none)"]
    prompt["format_context_window<br/>-> system prompt block"]
    fb["evictions/insertions -> events<br/>(feed AHE + calibration)"]

    evts --> Distill
    curmap --> Distill
    Distill --> distilled
    distilled --> Cart
    curmap --> Cart
    Cart --> result
    result --> render
    render --> prompt
    result -.-> fb
    fb -.-> evts
```

---

## 10. Skill & Tool Execution, Permissions vs Guards

Two complementary, **non-overlapping** enforcement systems. Notable asymmetry: skills invoked as
pydantic-ai tools (`type: skill` via `execute_skill_as_tool`) get `SkillPermissions` +
`BlackboardAccessProxy` but **bypass the guard pipeline entirely**; built-in tools and
skill-backed tools (`type: tool` via `ToolRunner`) get guards.

```mermaid
flowchart TD
    call["LLM tool call / /skill command"]

    subgraph Path1["Path 1: skill as pydantic-ai tool (type: skill)"]
        p1a["execute_skill_as_tool"]
        p1b["SkillRunner.execute_skill"]
        p1c["SkillPermissions.from_yaml"]
        p1d["BlackboardAccessProxy(db, perms)"]
        p1e["SkillContext (project_root/scratch gated)"]
        p1a --> p1b --> p1c --> p1d --> p1e
    end

    subgraph Path2["Path 2: built-in / skill-backed tool (type: tool)"]
        p2a["ToolRunner.execute_tool"]
        p2b["GuardPipeline.validate<br/>(Path, Size, Type, Idempotency, Content, Query)"]
        p2c{"skill-backed?"}
        p2d["handler(**kwargs) or handler(ToolContext)"]
        p2e["SkillRunner.execute_skill<br/>(perms apply here)"]
        p2a --> p2b --> p2c
        p2c -->|no| p2d
        p2c -->|yes| p2e
    end

    call --> Path1
    call --> Path2

    note1["Guards: NOT run on Path 1"]
    note2["Permissions: NOT on built-in tools,<br/>but YES on skill-backed (Path 2 yes)"]
    Path1 -.-> note1
    Path2 -.-> note2
```

Skill lifecycle (discovery -> compile -> preprocess -> execute):

```mermaid
flowchart TD
    disk[("SKILL.md on disk<br/>system_skills / project_skills")]
    parse["parse_skill_document<br/>frontmatter + body"]
    typ{"type?"}
    know["knowledge -> skill_catalog<br/><available_skills> block<br/>(progressive disclosure)"]
    toolreg["tool -> ToolRunner registry<br/>_skill_backed=True"]
    skillreg["skill -> SkillRunner.discover_skills<br/>-> pydantic-ai Tool"]
    compile["skill_compiler.compile_skill<br/>parse -> cluster -> extract -> verify"]
    bundle[("SkillBundle JSON cache<br/>full / partial / rejected")]
    pre["skill_preprocessing<br/>template vars + inline shell"]
    ctx["SkillContext<br/>+ BlackboardAccessProxy"]
    entry["skill.py execute(ctx, args)"]
    res["SkillResult<br/>success/failed/blocked/cancelled"]

    disk --> parse --> typ
    typ -->|knowledge| know
    typ -->|tool| toolreg
    typ -->|skill| skillreg
    disk --> compile --> bundle
    skillreg --> pre --> ctx --> entry --> res
    toolreg --> pre
```

---

## 11. Retrieval / RAG Pipeline

Documents are indexed at startup (auto-index of `docs/`) and on demand (CLI / search skill).
Embeddings are pre-computed at ingest; queries run hybrid (keyword + nearest-neighbor) against
Vespa. Project state is also indexed as keyword-only chunks.

```mermaid
flowchart TD
    subgraph Ingest["Ingest (startup auto-index / CLI)"]
        resolve["_resolve_files<br/>glob + ignore filters + ext allowlist"]
        hash["sha256 change detection<br/>vs DbDocumentSource.content_hash"]
        chunk["chunking<br/>text: sliding window<br/>PDF: pymupdf -> docling -> remote OCR"]
        embed["TextEmbedder<br/>snowflake-arctic-embed-l-v2.0 (1024-d)<br/>GPU fp16, normalized"]
        feed["LiveVespaDocumentClient.feed_chunks<br/>app.syncio.feed_data_point"]
        meta["persist DbDocumentSource / DbDocumentChunk"]
        state["index_project_state<br/>(keyword-only, embedding=[])"]
        resolve --> hash --> chunk --> embed --> feed --> meta
        state --> feed
    end

    subgraph Query["Query (search skill / CLI)"]
        req["SearchRequest<br/>{query, mode, hits, source_id?, kind?}"]
        qbody["_build_query_body<br/>keyword / semantic / hybrid (default)"]
        vespa["Vespa search<br/>ranking.profile: keyword|semantic|hybrid"]
        norm["_normalize_hit -> SearchResult"]
        req --> qbody --> vespa --> norm
    end

    V[(Vespa)]
    DB[(Blackboard)]

    feed --> V
    meta --> DB
    vespa --> V
    norm -->|"tool/skill output"| Model["LLM / agent"]
```

---

## 12. Durable State & Consolidation Flow

Session state accumulates as a `StatePayload` (notes/decisions/next_actions/open_questions/
constraints/changelog + facts). Consolidation is a proposal lifecycle: a session proposes a
snapshot; approval merges it into durable project state. Every mutation writes a `DbStateEvent`.

```mermaid
flowchart TD
    turn["per turn: append_session_state<br/>(section, text) -> dirty=True"]
    evt1[("DbStateEvent: append_<section>")]
    snap[("DbSessionSnapshot<br/>event-sourced projection<br/>via reducers.derive_session_state")]
    prop["create_state_proposal<br/>snapshot session state -> pending"]
    evt2[("DbStateEvent: proposal_created")]
    review["review: list_pending_proposals<br/>read_state_proposal"]
    approve{"approve / reject?"}
    merge["approve_state_proposal<br/>append_payload into project_state<br/>bump version, clear dirty"]
    evt3[("DbStateEvent: proposal_approved")]
    reject["reject_state_proposal"]
    evt4[("DbStateEvent: proposal_rejected")]
    ctx["build_state_context(project, session)<br/>-> LLM runtime-state string"]
    facts["set_project_fact / get_project_fact<br/>(direct, no proposal, writes fact_set event)"]

    turn --> evt1
    evt1 -.-> snap
    turn --> prop --> evt2
    prop --> review --> approve
    approve -->|approve| merge --> evt3
    approve -->|reject| reject --> evt4
    merge --> ctx
    facts --> ctx
    snap -.->|"processors consult<br/>stream_paused / failures"| proc["processors"]
```

---

## 13. AHE — Autonomous Harness Evolution

A self-improvement loop over the harness itself. Stages 1–3 are implemented (observe → diagnose
→ propose); stages 4–5 (apply / govern) are deferred behind governance tiers (`auto` vs `hitl`).

```mermaid
flowchart TD
    db[(Blackboard:<br/>DbContextMapEvent + DbStateEvent)]
    subgraph S1["Stage 1 — Telemetry"]
        agg["aggregate_telemetry<br/>(window_days=7)"]
        buckets["ContextMap / Delegation / Gate / Token / Execution"]
        persist1["persist_telemetry -> ahe:telemetry:cycle"]
        agg --> buckets --> persist1
    end
    subgraph S2["Stage 2 — Diagnose"]
        del1["delegate to harness_engineer subagent"]
        diag["Diagnosis{observed_problem,<br/>attributed_component, evidence}"]
        persist2["persist_diagnosis -> ahe:diagnosis:cycle"]
        del1 --> diag --> persist2
    end
    subgraph S3["Stage 3 — Propose"]
        del2["delegate to harness_engineer subagent"]
        prop["Proposal{target_component,<br/>proposed_change, governance_tier}"]
        persist3["persist_proposals -> ahe:proposal:id"]
        del2 --> prop --> persist3
    end
    subgraph S45["Stages 4-5 — Apply / Govern (deferred)"]
        gov["governance tiers: auto vs hitl"]
        apply["apply revisions (gated)"]
    end
    db --> S1
    S1 --> S2
    S2 --> S3
    S3 -.-> S45
```

---

## 14. Key Findings & Observations

### Architecture
- **Event-sourced blackboard core.** `EventBus` + `EventStore` persist every event to the
  `state_events` table (also the audit log for direct mutations). Processors/workers are async
  subscribers over `bus.subscribe_session()`. Session state is a snapshot + event-log projection
  (`reducers.derive_session_state`).
- **Two parallel agent loops.** `GoalRunner` (structured-decision LLM returning `GoalAction`,
  used by CLI/pipeline `agent` nodes) and `PydanticAgentRuntime` (native tool-calling, used by
  the `llm_worker` processor and `/mode chat`). They duplicate some concerns (token counting,
  stuck/retry policy).
- **v2 is a layered refactor on top of `core/*`, not a rewrite.** `v2/contracts/` is pure stdlib;
  every engine/handler/subscriber/wiring imports from `harness_poc.core.*` and reuses the v1
  `EventBus`/`EventStore`/`Database`/runtime/skills. Two modes: `react` (4 async workers) and
  `pipeline` (synchronous event-chained 3-step probe→execute→gate). Default `active_mode` is
  `react`, but `build_app_state` defaults `mode="chat"` so v2 is lazily built on `/mode` switch.
- **Context map is the per-turn orientation layer.** Materialized each cycle (distiller = 1 LLM
  call; cartographer = pure 5-stage), rendered into the system prompt every turn. Only verified
  code enters the v2 materialized map (gate-pass gated).
- **Capabilities are a leaf dependency.** `skills`/`tools`/`acdl` import almost nothing from
  other subsystems; runtime pulls them in. `acdl` is fully self-contained (a prompt-composition
  DSL, not an execution language).

### Enforcement model
- **Declarative per-skill permissions** (`SkillPermissions` via `BlackboardAccessProxy` +
  `SkillContext` workspace gating) vs **imperative per-call guards** (`GuardPipeline`:
  Path/Size/Type/Idempotency/Content/Query). Asymmetry: skills-as-tools bypass guards;
  built-in tools have no permissions (skill-backed tools get both).

### Latent issues worth verifying (not fixed per scope)
- `except ValueError, TypeError:` (Python-2 binding semantics, catches only the first type) in
  `runtime/message_history.py` (L34, L232), `tools/tool_runner.py` (`_accepts_context`,
  `_accepts_cancellation`), and `ahe/diagnose.py:85`, `ahe/propose.py:76` — the AHE ones are a
  `SyntaxError` at import time in modern Python and would block those modules from importing.
- `v2/workflow_orchestrator.py` calls `ExecutionEngine.spawn_sub_agent(..., background=...)` but
  the signature is `mode: Literal["foreground","background"]` — would raise `TypeError` on the
  non-empty-tasks path.
- `eval/judge.py` `_llm_rubric_eval` builds the LLM-judge prompt but never calls the model; it
  always falls back to the heuristic rubric. The "LLM-as-judge" is effectively heuristic today.
- `context_map/copt_gate.py` (MiniLM semantic-dedup) is not wired into the deterministic
  cartographer path (which dedups by exact `key`); it is an auxiliary hook.
- `max_background_agents` default differs: `build_execution_engine` (5) vs `ExecutionEngine.__init__` (8).

---

## 15. Presentation

- **In Zed:** this Markdown file renders all Mermaid diagrams inline (open
  `docs/architecture/core-infrastructure-diagrams.md`).
- **For presenting/sharing:** open `docs/architecture/diagrams.html` in any browser — a
  self-contained, styled, section-navigable Mermaid presentation (CDN-loaded, no install),
  printable to PDF.
```
