# Deverino

Deverino is a Python 3.14 proof-of-concept LLM agent harness. It combines a
Textual chat TUI, a Typer CLI, an event-sourced async runtime, project-local
skills, declarative workflows and pipelines, PostgreSQL-backed state,
Vespa-backed document retrieval, an index-time skill compiler, a FastAPI
dashboard with a Vue front-end, and a task-based evaluation framework.

The project is intentionally experimental, but the runtime pieces are concrete:
agents and tools communicate through typed durable events, skills use explicit
permission metadata, and document search returns cited chunks from a Vespa
schema built for hybrid retrieval. It also includes a PEEK-inspired context map:
an event-sourced orientation cache that is materialized in the background and
injected into the system prompt when available. An Agent Harness Evolution
(AHE) loop turns runtime telemetry into harness-level improvement proposals.

## Quickstart

Start the local backing services (Postgres + Vespa):

```bash
just services-up
just vespa-deploy
```

Postgres runs the `pgvector/pgvector:pg18` image so embedding columns are
available alongside the blackboard tables. Vespa can take a short time to become
ready before deployment succeeds. The application package lives in
`vespa/document_retrieval/` and is mounted into the container at `/vespa-app`.

Stop the services without deleting indexed state:

```bash
just services-down
```

PostgreSQL and Vespa data live in stable named volumes `deverino_pgdata` and
`deverino_vespadata`. Avoid `docker compose down -v` (or `podman compose down -v`)
unless you intentionally want to delete the database and Vespa index. The
Postgres container mounts the named volume at `/var/lib/postgresql` so the image
can manage its version-specific data subdirectory.

A second Postgres instance (`postgres_test`) is defined on port 5433 for the
test suite so tests never touch runtime state. It uses the
`deverino_pgdata_test` volume.

### Container runtime

The harness auto-detects your container backend — **Podman** on Linux,
**Docker** on macOS. The `Justfile` and `container_*` tools use whichever is
available. Install either:

- **Fedora:** `sudo dnf install podman podman-compose`
- **macOS:** `brew install --cask docker` (or Podman Desktop)

Run the harness:

```bash
# Start the Textual chat TUI
uv run harness-poc

# Show CLI commands
uv run harness-poc --help

# Run an autonomous event-sourced goal
uv run harness-poc goal "Summarize the ReAct prompting pattern" --max-iterations 5

# Run a deterministic workflow
uv run harness-poc workflow run research_task "What is the ReAct prompting pattern?"

# Run a declarative DAG pipeline
uv run harness-poc pipeline run research_and_write --input topic="black holes"

# Start the web dashboard (API + Vite dev proxy)
just dashboard

# Run the eval suite against the live agent
uv run harness-poc eval run --live
```

## Configuration

Main configuration lives in `harness.yaml`.

```yaml
version: 1.1

project:
  id: deverino

llm:
  provider: glm  # deepseek | openai | anthropic | glm
  model: glm-5.2
  base_url: https://open.bigmodel.cn/api/coding/paas/v4

paths:
  soul: harness_poc/system_prompts/SOUL.md
  # soul_compact: harness_poc/system_prompts/SOUL-compact.md  # token-efficient variant
  system_tools: harness_poc/system_tools
  system_skills: harness_poc/system_skills
  project_skills: skills
  personas: personas
  workflows: workflows
  pipelines: pipelines

runtime:
  database_url: postgresql://deverino:deverino@localhost/deverino
  default_container_image: deverino-python:latest
  container_ttl_seconds: 14400
  max_harness_containers: 5
  chat_history_max_tokens: 24000
  chat_history_recent_turns: 6
  tool_result_max_chars: 12000
  materializer_poll_interval: 30
  materializer_max_event_tokens: 8000
  materializer_token_budget: 1024
  materializer_freeze_threshold: 3
  materializer_freeze_seconds: 300
  materializer_copt_threshold: 0.92   # copt = change-over-prior-time freeze heuristic
  sub_agent_prompt_max_tokens: 4000

observability:
  logfire: true   # set to true and export LOGFIRE_TOKEN to enable
  logfire_include_content: false

compiler:
  enabled: true           # background skill compilation on TUI startup
  model: null             # null = use llm.model; override per provider/model
  provider: null          # null = use llm.provider
  be_enabled: false       # Stage 5: Binding Evidence (LLM prunes spurious contracts)
  rc_enabled: false       # Stage 6: Residual Cleanup (LLM fixes prose-contract mismatches)

tui:
  vim_enabled: true        # Vim-style modal editing in the Textual TUI (F2 toggles)
  vim_initial_mode: insert # insert | normal — starting mode when Vim is enabled

retrieval:
  enabled: true
  provider: vespa
  vespa_url: http://localhost:8080
  namespace: deverino
  schema: doc_chunk
  default_hits: 8
  default_mode: hybrid
  chunk_size_chars: 1800
  chunk_overlap_chars: 200
  max_feed_workers: 1
  max_file_bytes: 52428800
  query_timeout_seconds: 5
  auto_index_paths:
    - docs/
  auto_index_ignore_paths:
    - docs/acdl
    - dashboard-ui/node_modules
    - node_modules
    - .venv
    - __pycache__

distiller:
  model: glm/glm-5.2
  max_retries: 3
  prompt_template: distiller_v2          # includes architecture + obsolete signals
  # prompt_template_compact: distiller_v2_compact  # token-efficient variant
  timeout_seconds: 120                   # per-attempt LLM call timeout

cartographer:
  token_budget: 1024
  tokenizer_name: cl100k_base

  # Per-type decay — each observation type has its own staleness/recency curve.
  # (architecture is long-lived; result is volatile.) `staleness_penalty` shown
  # in block form; the other three use YAML flow-mapping for the same 8 types.
  staleness_penalty:
    dispute: 0.02
    schema: 0.03
    insight: 0.05
    architecture: 0.01
    boundary: 0.02
    entity: 0.05
    result: 0.10
    constant: 0.01
  staleness_floor:   { dispute: 0.50, schema: 0.40, insight: 0.20, architecture: 0.60, boundary: 0.30, entity: 0.20, result: 0.05, constant: 0.60 }
  recency_bonus:     { dispute: 0.01, schema: 0.01, insight: 0.01, architecture: 0.01, boundary: 0.01, entity: 0.01, result: 0.00, constant: 0.01 }
  recency_cap:       { dispute: 0.50, schema: 0.50, insight: 0.40, architecture: 0.80, boundary: 0.30, entity: 0.50, result: 0.10, constant: 0.30 }

  priority_weights:
    dispute: 1.0
    schema: 0.9
    architecture: 0.85
    insight: 0.8
    boundary: 0.7
    entity: 0.6
    result: 0.5
    constant: 0.4

  section_budget_share:   # how the token budget is split across rendered sections
    context_architecture: 0.25
    parsing_schema: 0.20
    context_understanding: 0.25
    context_roadmap: 0.15
    domain_constants: 0.10
    reusable_results: 0.05

  cross_corpus:
    enabled: true
    related_corpora:
      "deverino:codebase":
        - "deverino:dashboard"
        - "deverino:benchmarks"
    max_cross_entries: 16
    min_priority: 0.7
```

The `distiller:` and `cartographer:` blocks configure the two-stage context-map
pipeline. Distiller is an LLM pass that extracts observations from event
batches; Cartographer is a deterministic Python scorer that ranks and evicts
entries against a token budget. The `compiler:` block controls the skill
compiler (see [Skill Compiler](#skill-compiler)).

API keys are read from environment variables or a project-root `.env` file:

| Provider    | Env var             |
| ----------- | ------------------- |
| `deepseek`  | `DEEPSEEK_API_KEY`  |
| `openai`    | `OPENAI_API_KEY`    |
| `anthropic` | `ANTHROPIC_API_KEY` |
| `glm`       | `GLM_API_KEY`       |

If no key is available for the configured provider, Deverino falls back to mock
LLM responses so local tests and UI flows can still run.

## Document Retrieval

Document retrieval is backed by Vespa. PostgreSQL stores source metadata,
content hashes, chunk counts, and indexing status; Vespa stores and searches the
chunk documents.

The current retrieval stack includes:

- `RetrievalConfig` in `harness.yaml`
- metadata tables for document sources and chunks
- `DocumentIndexer` with content-hash skipping, ignored-directory handling, and
  path allowlist checks
- `LiveVespaDocumentClient` for health checks, feeding, deletion, and search
- a Vespa application package under `vespa/document_retrieval/`
- `index_documents` and `search_documents` skills
- a dedicated `documents index` CLI command

Supported source formats include text-like project files such as `.md`, `.txt`,
`.rst`, `.yaml`, `.json`, `.toml`, `.py`, and `.pdf`. PDF files are extracted to
text with page markers before chunking.

Index a PDF:

```bash
uv run harness-poc documents index docs/papers/2605.20173.pdf
```

Index a directory of PDFs:

```bash
uv run harness-poc documents index docs --glob "*.pdf"
```

Force reindexing even when content hashes have not changed:

```bash
uv run harness-poc documents index docs/papers/2605.20173.pdf --force
```

Skip generated or non-prose directories while indexing:

```bash
uv run harness-poc documents index docs --exclude-dir docs/acdl
```

From the TUI, ask the agent to use retrieval skills directly:

```text
Use index_documents with {"paths":["docs", "README.md"], "exclude_dirs":["docs/acdl"]}
Use search_documents with {"query":"state consolidation proposals","mode":"hybrid","hits":5}
```

Search results are formatted as cited chunks such as `docs/example.md#chunk-2`.

## PEEK Context Map

Deverino implements an event-sourced version of the PEEK context map idea: a
small, fixed-budget orientation cache that helps the agent remember how to
navigate a corpus without stuffing full retrieval traces into every prompt.

The implementation keeps the PEEK pipeline shape while decoupling it from the
foreground chat loop:

```text
agent/tool activity
  -> typed context-map events in PostgreSQL
  -> Distiller (LLM)  — extracts observations from event batches
  -> Cartographer (deterministic) — priority queue with budget enforcement
  -> Evictor (deterministic) — removes lowest-priority entries on overflow
  -> compact context_map row, materialized via background poller
  -> next app/session prompt includes the stored map
```

Current context-map components:

- typed Pydantic event models in `harness_poc/core/events/context_map_events.py`
- pipeline schema in `harness_poc/core/context_map/schema.py`
  (`DistillerEntry`, `DistilledBatch`, `MapEntry`, `EvictionRecord`,
  `CartographerResult`)
- PostgreSQL tables `context_map_events` and `context_map`
- LLM-driven `Distiller` in `harness_poc/core/context_map/distiller.py`
  with retry/repair and structured output
- deterministic `Cartographer` in `harness_poc/core/context_map/cartographer.py`
  that scores entries by `priority_weight × recency × (1 − staleness)`
- deterministic Evictor (in the same module) that drops the lowest-priority
  entries when the token budget is exceeded
- `context-map-materializer` project skill that orchestrates one full
  Distiller → Cartographer → Evictor pass for a corpus key
- `MaterializerRunner`, started by the TUI and main async runtime, which polls
  pending corpus keys
- `append_event` system skill for manually appending typed events
- `observe` project skill — emits structured observations with 9 types
  (entity, schema, insight, dispute, boundary, constant, result, architecture,
  obsolete)
- **automatic post-turn observation extraction**: signal-tool turns
  (e.g. `semble_search`, `read_file`, `search_documents`,
  `consolidate_state`) are summarized by a background classifier and fed
  through `observe` without the agent having to ask. See
  `pydantic_runtime.py:extract_observations_from_turn`.
- `search_documents` and `search_failed` events from retrieval skills
- prompt injection of the stored context map during app-state creation

The materializer avoids repeated LLM calls when a corpus is stable. Each skill
run reports whether the persisted map actually changed; after
`runtime.materializer_freeze_threshold` consecutive no-change cycles, the runner
sets `context_map.freeze_until` for `runtime.materializer_freeze_seconds`. A
second heuristic, `materializer_copt_threshold` (change-over-prior-time),
freezes corpora whose edit volume has dropped below a ratio of the prior window.
Pending events are left unprocessed during a freeze and are picked up after it
expires.

Map entries (`MapEntry` in `core/context_map/schema.py`) carry stable
8-character `entry_id` values, observation type, summary, source event IDs,
materialization count, cycle bounds, and a token estimate. Priority is
recomputed each cycle from configurable `priority_weights`, recency bonus, and
staleness penalty. **Decay is per-type** — eight observation types (dispute,
schema, insight, architecture, boundary, entity, result, constant) each have
their own `staleness_penalty`, `staleness_floor`, `recency_bonus`, and
`recency_cap` in `harness.yaml`, so long-lived architectural facts decay slowly
while volatile results age out fast. (`obsolete` entries have no decay curve —
they are treated as already-stale.) The rendered map splits its token budget
across sections (`section_budget_share`) and can pull in related entries from
other corpora (`cross_corpus`).

Context maps are keyed by corpus, using the configured project id. App startup
currently injects the `deverino:default` map when present; `search_documents`
emits document-retrieval events under `deverino:codebase`. Use the `list_corpora`
tool to discover valid corpus keys before observing or citing into a corpus.

Priority weights can be calibrated from observed reference/eviction rates. The
`cartographer calibrate` CLI command reads `MapEntryReferenced`,
`MapEntryEvicted`, and `MapEntryInserted` events from the event log over a
configurable window and computes target weights deterministically.

```bash
# Dry run — print the target weights and deltas
uv run harness-poc cartographer calibrate --window-days 14

# Apply — write new weights to harness.yaml
uv run harness-poc cartographer calibrate --apply
```

The manual event skill accepts explicit corpus keys:

```text
/skill append_event {
  "event_type":"entity_referenced",
  "corpus_key":"deverino:default",
  "payload":{
    "entity_name":"DocumentIndexer",
    "entity_type":"class",
    "context":"Coordinates file chunking, Vespa feed, and PostgreSQL metadata."
  }
}
```

Run the materializer directly when you do not want to wait for the background
poller:

```text
/skill context-map-materializer {"corpus_key":"deverino:default","token_budget":1024}
```

## Skill Compiler

The skill compiler (`harness_poc/core/skills/skill_compiler.py`) is an index-time
pipeline that turns each `SKILL.md`'s prose into a structured `SkillBundle`. The
bundle drives progressive disclosure: the LLM sees compact contract signatures
by default and only loads full prose on demand, cutting prompt tokens.

Stages:

1. **Parser** — extract procedural units from the markdown body
2. **Clustering** — per-skill similarity grouping (sentence-transformer embeddings)
3. **Contract Extractor** — LLM generates `TypedContract`s per cluster
4. **Verifier** — deterministic coverage, binding, replacement, and risk checks
5. **Binding Evidence (BE, optional)** — LLM prunes spurious call-sites
   (`compiler.be_enabled`)
6. **Residual Cleanup (RC, optional)** — LLM fixes prose/code conflicts
   (`compiler.rc_enabled`)

Compilation is mtime-triggered and runs in the background on TUI startup when
`compiler.enabled` is true. The dashboard exposes live progress and per-skill
results (see [Dashboard & HTTP API](#dashboard--http-api)).

## Dashboard & HTTP API

`harness_poc/api/` is a FastAPI application that exposes a read-only view of the
blackboard plus skill-compilation endpoints. It is the back-end for the web
dashboard.

```bash
uv run harness-poc dashboard summary            # terminal snapshot
uv run harness-poc dashboard serve              # FastAPI on :8050
uv run harness-poc dashboard serve --debug      # auto-reload
```

Selected endpoints (all under `/api`):

| Endpoint | Purpose |
| --- | --- |
| `/api/overview` | Dashboard snapshot (sessions, tokens, errors) |
| `/api/sessions`, `/api/sessions/{id}/events` | Session activity and event rows |
| `/api/events/recent`, `/api/events/stream` | Recent events + Server-Sent Events stream |
| `/api/context-maps`, `/api/context-maps/{key}/entries` | Context-map health and entries |
| `/api/skills`, `/api/skills/progress` | Skill compilation summaries and live progress |
| `/api/skills/compile`, `/api/skills/{name}/compile` | Trigger background compilation |
| `/api/skills/compile/stream` | SSE stream of per-skill compilation events |
| `/api/subagents/tree` | Delegated sub-agent tree |
| `/api/tokens/economics`, `/api/tokens/usage` | Token bucket and model usage |
| `/api/state/project`, `/api/state/events`, `/api/state/proposals` | Durable state and consolidation |

The front-end lives in `dashboard-ui/` — a Vue 3 app (TDesign chat, ECharts,
Pinia, Tailwind) with views for Overview, Sessions, Chat, Context Map, Skills,
State, Sub-Agents, and Tokens. During development run the API and the Vite dev
server in parallel so `/api` is proxied:

```bash
just dashboard-dev          # API with reload on :8050
just dashboard-ui-dev       # Vite dev server on :5173 (proxies /api → :8050)
just dashboard-build        # production build into dashboard-ui/dist/
```

## Evaluation Framework

Deverino ships a task-based eval harness in `harness_poc/core/eval/` with task
definitions in `evals/tasks/` and scored reports written to `evals/results/`.
Each task is a YAML file with a prompt, optional file context, a category, and
rubric traits. A `JudgeEvaluator` scores agent output against the rubric and
produces a pass/fail per task plus an aggregate report. Reports can gate CI via
a non-zero exit code when any task falls below `min_score`.

```bash
uv run harness-poc eval run                       # all tasks (offline placeholder)
uv run harness-poc eval run --task code_explain_config_model
uv run harness-poc eval run --category file_operations
uv run harness-poc eval run --live                # execute through the real agent
```

`--live` runs each prompt through `PydanticAgentRuntime.run_text` (single-turn
chat mode with transparent tool access) and scores the result. Baseline runs are
kept in `evals/baselines/`.

## Agent Harness Evolution (AHE)

AHE (`harness_poc/core/ahe/`) is a harness-level optimization loop: it observes
runtime behaviour, diagnoses harness-level problems, and proposes improvements.
The pipeline mirrors the agent loop but operates on the harness itself.

- **Stage 1 — Telemetry** (`telemetry.py`): aggregates context-map, delegation,
  execution, gate, and token telemetry into a `TelemetrySummary` and persists it.
- **Stage 2 — Diagnosis** (`diagnose.py`): delegates analysis to a
  `harness_engineer` sub-agent that attributes observed problems to specific
  harness components.
- **Stage 3 — Propose** (`propose.py`): generates concrete change proposals from
  the diagnosis.

The `ahe_evolve` system skill orchestrates a full cycle. See
`docs/superpowers/specs/2026-06-22-ahe-evolution-agent-design.md` for the design.

## Subagents

Sub-agents are persona-scoped LLM sessions spawned by the `delegate_task` system
skill. Persona definitions live in two places:

- `subagents/*.yml` — role prompts for architect, code_reviewer, data_validator,
  harness_engineer, test_reviewer, ux_reviewer, web_researcher
- `agents/roles/<role>/` — role-specific skill/prompt assets

Delegation is typed end-to-end: the v2 contracts in `harness_poc/v2/contracts/`
define `SubAgentSpawner`, `DelegatedTaskResult`/`DelegatedTaskOutput`, and the
canonical status mappings (goal → delegated → external). The
`delegate_task_handler` in `harness_poc/v2/handlers/` spawns the sub-agent,
writes the result to the blackboard, and emits `SubAgentTaskStarted` /
`SubAgentTaskCompleted` events. The dashboard renders the delegation tree via
`/api/subagents/tree`.

## CLI

```bash
# Start the interactive TUI
uv run harness-poc

# Explicit REPL/TUI command
uv run harness-poc repl

# Goal execution
uv run harness-poc goal "Summarize the event-sourced architecture" --max-iterations 10
uv run harness-poc goal "Summarize retrieval" --max-tokens 8000 --max-seconds 60

# Documents
uv run harness-poc documents index docs/papers/2605.20173.pdf
uv run harness-poc documents index docs --glob "*.md" --force
uv run harness-poc documents index docs --exclude-dir docs/acdl

# Skills and tools
uv run harness-poc skill list
uv run harness-poc skill show index_documents
uv run harness-poc skill show context-map-materializer
uv run harness-poc tool list

# State
uv run harness-poc state show project
uv run harness-poc state show session
uv run harness-poc state consolidate preview

# Events
uv run harness-poc events --limit 10
uv run harness-poc events --session-id <id> --follow --type LLMActionEmitted

# Workflows and pipelines
uv run harness-poc workflow run research_task "What is the ReAct pattern?"
uv run harness-poc pipeline list
uv run harness-poc pipeline run research_and_write --input topic="black holes"

# Dashboard
uv run harness-poc dashboard summary
uv run harness-poc dashboard serve

# Evaluations
uv run harness-poc eval run --live
uv run harness-poc eval run --task code_explain_config_model

# Cartographer calibration
uv run harness-poc cartographer calibrate --window-days 14
uv run harness-poc cartographer calibrate --apply

# ACDL inspection (parse .acdl spec files)
uv run harness-poc acdl inspect path/to/spec.acdl
```

## TUI Commands

`uv run harness-poc` starts the Textual chat interface. It streams model output,
shows tool progress separately from assistant text, and tracks session token
usage. Vim-style modal editing is available (toggle with F2).

Useful slash commands:

```text
/pipeline <name> [key=value ...]
/pipelines
/workflow <name> <objective>
/workflows
/goal <objective>
/skill list
/skill show <name>
/skill <name> {"key":"value"}
/state show [project|session|all]
/state consolidate [preview|propose|approve]
/copy
/help
/exit
```

## Architecture

```text
harness_poc/
├── cli.py                  # Typer CLI
├── repl.py                 # TUI command handling and direct skill dispatch
├── tui.py                  # Textual chat application
├── tui_vim.py              # Vim modal editing for the TUI
├── repl_completion.py      # Slash-command completion
├── app_factory.py          # Runtime wiring into AppState
├── console.py              # Rich console helpers
├── dashboard_theme.py      # Terminal dashboard theme
├── api/                    # FastAPI dashboard + chat back-end
│   ├── __init__.py         # create_app / create_app_from_config
│   ├── routes.py           # read-only blackboard + skill-compile endpoints
│   └── chat.py             # chat router
├── core/
│   ├── config.py           # YAML/.env config loading
│   ├── logging.py          # Logging configuration
│   ├── permissions.py      # Permission model
│   ├── acdl/               # ACDL parser, AST, executor, and CLI
│   ├── ahe/                # Agent Harness Evolution (telemetry, diagnose, propose)
│   ├── eval/               # Evaluation framework (task, judge, runner, refine)
│   ├── observe/            # Structured observability (log_tap, timing, trace)
│   ├── events/             # Typed event hierarchy and async pub/sub
│   │   ├── events.py       # Event dataclasses and registry
│   │   ├── event_bus.py    # Sync/async pub/sub
│   │   ├── event_store.py  # Durable event persistence
│   │   ├── event_log_observer.py # Event log tailing
│   │   └── context_map_events.py # PEEK-style context-map event models
│   ├── context_map/        # Deterministic cartographer pipeline
│   │   ├── schema.py       # DistillerEntry, MapEntry, EvictionRecord
│   │   ├── distiller.py    # LLM extraction with retry/repair
│   │   ├── cartographer.py # Deterministic priority queue + evictor
│   │   ├── calibrate.py    # priority_weights calibration
│   │   ├── render.py       # Map → prompt-fragment rendering
│   │   ├── sections.py     # Section layout helpers
│   │   └── prompts/        # Distiller prompt templates
│   ├── execution/          # Declarative execution engines
│   │   ├── pipeline_runner.py    # Wave-based DAG execution
│   │   ├── workflow_runner.py    # YAML workflow execution
│   │   └── materializer_runner.py # Background context-map materializer poller
│   ├── observability/      # Telemetry and dashboards
│   │   ├── dashboard.py    # Summary and live dashboard data fetchers
│   │   └── logfire_subscriber.py # Logfire event forwarding
│   ├── processors/         # LEGACY v1 workers (used by `goal` without --refine)
│   │   ├── llm_worker.py
│   │   ├── tool_worker.py
│   │   ├── circuit_breaker.py
│   │   └── processor_supervisor.py
│   ├── retrieval/          # Document retrieval stack
│   │   ├── retrieval.py    # Domain models and chunking
│   │   ├── document_index.py # File/PDF indexing into retrieval chunks
│   │   ├── vespa_client.py # pyvespa adapter
│   │   └── pdf_converter.py # PDF-to-text extraction
│   ├── runtime/            # LLM execution and agent loop
│   │   ├── goal_runner.py  # Autonomous ReAct loop
│   │   ├── pydantic_runtime.py # PydanticAI streaming/tool runtime
│   │   ├── llm_client.py   # Provider-agnostic LLM client
│   │   ├── message_history.py  # Conversation history management
│   │   ├── reducers.py     # Snapshot derivation from event history
│   │   └── token_accounting.py # Token budget tracking
│   ├── skills/             # Skill discovery, compilation, and execution
│   │   ├── skill_runner.py # SKILL.md discovery/execution
│   │   ├── skill_catalog.py # Skill registry
│   │   ├── skill_compiler.py # 6-stage pseudocode → SkillBundle pipeline
│   │   ├── skill_bundle.py  # Compiled SkillBundle / TypedContract models
│   │   ├── skill_context.py # SkillContext/SkillResult types
│   │   ├── skill_preprocessing.py # Argument preprocessing
│   │   └── skill_scaffolder.py # `skill create` scaffold generator
│   ├── storage/            # PostgreSQL blackboard and state
│   │   ├── database.py     # BlackboardDatabase and metadata access
│   │   ├── db_engine.py    # SQLAlchemy engine setup
│   │   ├── models.py       # ORM table definitions
│   │   ├── state.py        # Session/project state helpers
│   │   └── blackboard_proxy.py # Skill-facing blackboard facade
│   └── tools/              # Built-in tool infrastructure
│       ├── tool_runner.py  # Tool discovery/execution + input guards
│       ├── guards.py       # Guard pipeline run before tool execution
│       ├── tool_context.py # ToolContext type
│       └── tool_result.py  # ToolResult type
├── v2/                     # Active orchestration layer (react/pipeline modes)
│   ├── subscribers/        # ReAct bus workers: llm_worker, tool_worker, circuit_breaker, goal_evaluator, pipeline_runner
│   ├── contracts/          # Typed protocols: context_map_pipeline, event_runtime, sub_agent_spawner
│   ├── handlers/           # delegate_task_handler (sub-agent lifecycle)
│   ├── execution_engine.py, workflow_orchestrator.py, context_engine.py
│   └── wiring.py           # build_v2_runtime — assembles subscribers per mode
├── system_tools/           # Built-in LLM-callable primitives
│   ├── file_tools.py       # read_file, write_file, patch, apply_diff, search_files, view_file, search_in_file
│   ├── container_spawn.py, container_exec.py, container_destroy.py
│   ├── execute_python.py
│   ├── read_memory.py
│   ├── knowledge_tools.py  # skills_list, skill_view, skill_manage (progressive disclosure)
│   ├── corpus_tools.py     # list_corpora
│   ├── read_project_state.py, set_project_fact.py, append_session_state.py
│   ├── acdl_tools.py       # acdl_inspect
│   └── inspect_context.py  # inspect_own_context
├── system_skills/          # System agent skills (delegate_task, evaluate_goal, evaluate_output, consolidate_state, orchestrate, ahe_evolve, ...)
└── system_prompts/         # SOUL.md (and SOUL-compact.md) primary system prompt

skills/                     # Project-local tools, skills, and knowledge skills
workflows/                  # YAML workflow definitions
pipelines/                  # YAML pipeline DAG definitions
personas/                   # Prompt templates for sub-agents
subagents/                  # Sub-agent persona YAML (architect, code_reviewer, ...)
agents/roles/               # Per-role skill/prompt assets
evals/                      # Eval task definitions, baselines, and results
dashboard-ui/               # Vue 3 dashboard front-end
acdl-visualizer/            # Static HTML/JS ACDL spec visualizer
vespa/document_retrieval/   # Vespa app package for doc_chunk retrieval
```

## Runtime Model

Interaction is event-sourced on a shared `EventBus` / `EventStore`:

```text
AgentInputAdded
  -> LLM worker emits LLMActionEmitted, SkillRequested, or LLMTextEmitted
  -> tool worker executes requested skills and emits SkillCompleted
  -> circuit breaker watches token/failure budgets and emits StreamPaused
```

This loop runs in one of two layers, chosen by `AppState.active_mode`:

- **v2 (`harness_poc/v2/`, active)** — `react` (the default) and `pipeline` modes
  wire `v2/subscribers/` plus the execution-engine / workflow-orchestrator /
  context-engine. v2 builds on the shared `core/` foundation rather than forking
  it. Plain REPL/TUI input runs the v2 react loop; `/mode chat` is an escape
  hatch that streams directly through `PydanticAgentRuntime` with native tools.
  Cross-component boundaries are codified as typed protocols in `v2/contracts/`,
  and concrete handlers (e.g. `delegate_task_handler`) live in `v2/handlers/`.
- **v1 (`core/processors/`, legacy)** — the same worker shape as free functions,
  still used by `harness-poc goal` (without `--refine`). v2's subscribers are a
  superset (they carry the context-map citation tracking and skill cancellation).

Events are Pydantic models persisted through `EventStore` and published through
`EventBus`. Reducers derive session snapshots from durable events so workers can
rebuild state without holding private cross-loop mutable state. The system prompt
itself is composed from the executable `deverino_react.acdl` spec (see
`core/acdl/executor.py`).

The context-map subsystem uses its own event log in the blackboard.
Tool and skill activity (plus the auto-observe post-turn hook) appends
typed orientation events. The background materializer runs a two-stage
pipeline: an LLM Distiller extracts observations into `DistillerEntry`
records, then a deterministic Python Cartographer scores and evicts
entries against a token budget. The materialized map is loaded into
future system prompts. This map is a cache, not a source of truth; if
materialization fails, events remain unprocessed and are retried on
the next poll. Stable maps can be temporarily frozen to save Distiller
LLM calls.

Pipeline agent nodes and `harness-poc goal --refine` use the `GoalRunner` path,
which includes semantic retry detection, context-window compression, budget
enforcement, and `evaluate_goal` interception.

## Tools, Skills, And Knowledge

Deverino separates four kinds of callable/project knowledge:

- **Built-in tools** are pure primitives registered in `harness_poc/system_tools/`.
- **Tool skills** are `SKILL.md` packages with `type: tool`, often project-local
  in `skills/`.
- **Agent skills** are orchestration capabilities with `type: skill`; they may
  call LLMs, spawn sub-agents, or manage multi-step state.
- **Knowledge skills** are markdown instruction documents with `type: knowledge`;
  they are loaded on demand as context, not executed.

Selected built-in tools:

| Name | Purpose |
| --- | --- |
| `read_file`, `write_file`, `patch`, `apply_diff` | Workspace file read/edit |
| `view_file`, `search_in_file` | Targeted line-range view and in-file search |
| `search_files` | ripgrep content/file search (gitignore-aware) |
| `container_spawn`, `container_exec`, `container_destroy` | Docker/Podman sandbox management |
| `execute_python` | Run Python in a session-scoped container |
| `read_memory` | Read blackboard memory |
| `skills_list`, `skill_view`, `skill_manage` | Progressive disclosure + management of knowledge skills |
| `read_project_state`, `set_project_fact`, `append_session_state` | Durable project + session state |
| `list_corpora` | Inventory context-map corpora and pending events |
| `append_event` | Append typed context-map events |
| `inspect_own_context` | Return the agent's own assembled system prompt |
| `acdl_inspect` | Parse an ACDL spec file and return a structured summary |

Selected tool/agent/knowledge skills (project-local in `skills/` unless noted):

| Name | Kind | Purpose |
| --- | --- | --- |
| `semble_search` | tool | Semantic code search (semble) |
| `web_search` | tool | LangSearch-backed web search |
| `index_documents` | tool | Feed project documents into Vespa |
| `search_documents` | tool | Search indexed Vespa chunks |
| `observe` | tool | Record structural observations for the context map |
| `context-map-materializer` | skill | Materialize context-map events into a prompt cache |
| `review_work` | skill | Review the current working tree |
| `trace_session` | skill | Trace an event-sourced session |
| `inspect_db` | skill | Inspect the blackboard database |
| `find_error_pattern` | skill | Cluster and surface recurring error patterns |
| `delegate_task` (system) | skill | Spawn a persona-specific sub-agent |
| `evaluate_goal` (system) | skill | Structured goal completion/blockage signal |
| `evaluate_output` (system) | skill | Judge output against an objective |
| `consolidate_state` (system) | skill | Preview, propose, or approve state consolidation |
| `orchestrate` (system) | skill | Multi-step task orchestration |
| `ahe_evolve` (system) | skill | Run an AHE evolution cycle |
| `summarize_memory` | skill | Summarize a blackboard memory key |
| `reflect_on_result` | skill | Judge whether a result satisfies an objective |
| `spec_writer` | skill | Gather requirements and draft implementation specs |
| `create_rubrics` | skill | Generate benchmark rubrics from behaviour descriptions |
| `paper-catalog` | skill | Catalog indexed papers |
| `paper-claim-verification` | skill | Verify design-doc paper citations against indexed papers |
| `developer-pedagogy` | knowledge | Project knowledge about developer preferences and constraints |
| `deverino-react-acdl` | knowledge | ACDL description of the Deverino ReAct loop |
| `acdl-syntax`, `acdl-tooling` | knowledge | ACDL grammar quickstart and tooling |
| `deterministic-cartographer` | knowledge | Design rationale for the deterministic Cartographer |

## Workflows And Pipelines

Workflows are deterministic YAML state machines in `workflows/`. Each state calls
a skill and passes output to the next state through template variables.

```bash
uv run harness-poc workflow run research_task "What is the ReAct pattern?"
```

Pipelines are DAGs in `pipelines/`. They support parallel waves, skill nodes,
and autonomous agent nodes.

```bash
uv run harness-poc pipeline run research_and_write --input topic="black holes"
```

Pipeline nodes without unresolved dependencies run concurrently via a thread
pool. Failed nodes mark dependents as skipped without aborting unrelated nodes in
the same wave.

## Spec Writer

`spec_writer` supports a gather/draft flow for implementation specs.

Gather requirements:

```text
/skill spec_writer {"mode":"gather","gather_key":"my_spec"}
```

Draft from gathered context:

```text
/skill spec_writer {"mode":"draft","gather_key":"my_spec","use_llm":true}
```

The skill writes generated specs to `specs/` and stores outputs in the
blackboard.

## Observability

Set `observability.logfire: true` and provide `LOGFIRE_TOKEN` to forward EventBus
events to Logfire. `logfire_include_content` controls whether event content is
included in telemetry. Structured tracing helpers (timing, log tap, trace spans)
live in `harness_poc/core/observe/`.

```bash
export LOGFIRE_TOKEN=<your-token>
uv run harness-poc
```

## Development

```bash
uv run ruff check .    # lint
uv run ty check        # type check
just check             # lint + types + tests
```

## Testing

Three layers. Each has one job. Each runs independently.

```
┌──────────┐     ┌──────────┐     ┌──────────┐
│   unit   │     │  agent   │     │  bench   │
│          │     │          │     │          │
│ pure fn  │     │ mock LLM │     │  Postgres│
│ + SQLite │     │ + SQLite │     │  + LLM   │
└──────────┘     └──────────┘     └──────────┘
     │                │                │
     ▼                ▼                ▼
  functions       goal loop         quality
  & parsing       behaviour         scoring
```

| Layer | Runs | What it validates |
|-------|------|-------------------|
| `tests/unit/` | `just test-unit` | Pure functions, parsing, events, database operations |
| `tests/agent/` | `just test-agent` | GoalRunner loop behaviour with a mock LLM |
| `tests/bench/` | `just test-bench` | Agent output quality against rubrics with a real LLM |

Tests that touch Postgres use the dedicated `postgres_test` service on port 5433
via `TEST_DATABASE_URL`. The `just test` / `just test-file` recipes start that
container automatically.

```bash
just test-db-up                                   # start the test database
just test-unit                                    # fast tests, no DB / no LLM
uv run pytest tests/unit/ tests/agent/            # all fast tests
just test-integration                             # needs Postgres + Vespa
just test-bench                                   # real LLM (costs tokens)
```

Benchmarks are opt-in (real LLM costs tokens):

```bash
just test-bench                                   # default model
just test-bench claude-haiku-4-5-20251001        # override model
```

Generate benchmark rubrics from natural-language descriptions with the
`create_rubrics` skill instead of writing `.md` files by hand:

```text
/skill create_rubrics description="..." goal="..."
/skill create_rubrics confirm=true slug="my-slug"
```

Full testing guide: [`tests/GUIDE.md`](tests/GUIDE.md)

`create_rubrics` usage guide: [`docs/superpowers/specs/2026-05-23-create-rubrics-usage.md`](docs/superpowers/specs/2026-05-23-create-rubrics-usage.md)

## Creating Skills

Skills use this contract:

```python
def execute(ctx: SkillContext, arguments: dict[str, Any]) -> SkillResult:
    ...
```

Each skill directory usually contains:

- `SKILL.md` with YAML frontmatter: `name`, `description`, `type`,
  `parameters`, `auto_invokable`, `entrypoint`, and `permissions`
- `skill.py` with the `execute()` implementation
- optional support files

Create a project-local skill scaffold:

```bash
uv run harness-poc skill create my_skill "Short description"
```

Compiled `SkillBundle`s are produced by the [Skill Compiler](#skill-compiler) and
power progressive disclosure (`skills_list` / `skill_view`).

## Container Sandbox

Container-backed tools use Docker or Podman. The default image is
`deverino-python:latest`, built from the project `Dockerfile` on first use if it
is not already available.

Change the default image in `harness.yaml`:

```yaml
runtime:
  default_container_image: deverino-python:latest
```
