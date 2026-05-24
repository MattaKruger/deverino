# Deverino

Deverino is a Python 3.14 proof-of-concept LLM agent harness. It combines a
Textual chat TUI, a Typer CLI, an event-sourced async runtime, project-local
skills, declarative workflows and pipelines, PostgreSQL-backed state, and
Vespa-backed document retrieval.

The project is intentionally experimental, but the runtime pieces are concrete:
agents and tools communicate through typed durable events, skills use explicit
permission metadata, and document search returns cited chunks from a Vespa
schema built for hybrid retrieval. It also includes a PEEK-inspired context map:
an event-sourced orientation cache that is materialized in the background and
injected into the system prompt when available.

## Quickstart

Start the local backing services:

```bash
docker compose up -d postgres vespa
docker compose exec vespa vespa deploy /vespa-app
```

Vespa can take a short time to become ready before deployment succeeds. The
application package lives in `vespa/document_retrieval/` and is mounted into the
container at `/vespa-app`.

Stop the services without deleting indexed state:

```bash
docker compose stop
```

PostgreSQL and Vespa data live in stable named Docker volumes
`deverino_pgdata` and `deverino_vespadata`. Avoid `docker compose down -v`
unless you intentionally want to delete the database and Vespa index.
The Postgres 18 container mounts the named volume at `/var/lib/postgresql` so
the image can manage its version-specific data subdirectory.

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
```

## Configuration

Main configuration lives in `harness.yaml`.

```yaml
version: 1.1

project:
  id: deverino

llm:
  provider: deepseek  # deepseek | openai | anthropic
  model: deepseek-v4-pro

paths:
  soul: harness_poc/system_prompts/SOUL.md
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

observability:
  logfire: true
  logfire_include_content: false

tui:
  vim_enabled: true
  vim_initial_mode: insert

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
  max_feed_workers: 8
  max_file_bytes: 52428800
  query_timeout_seconds: 5
  auto_index_paths:
    - docs/
  auto_index_ignore_paths:
    - docs/acdl

distiller:
  model: anthropic/claude-haiku-4-5
  max_retries: 3
  prompt_template: distiller_v1

cartographer:
  token_budget: 1024
  tokenizer_name: cl100k_base
  recency_bonus: 0.01
  recency_cap: 0.5
  staleness_penalty: 0.05
  staleness_floor: 0.2
  priority_weights:
    dispute: 1.0
    schema: 0.9
    insight: 0.8
    boundary: 0.7
    entity: 0.6
    result: 0.5
    constant: 0.4
```

The `distiller:` and `cartographer:` blocks configure the two-stage context-map
pipeline. Distiller is an LLM pass that extracts observations from event
batches; Cartographer is a deterministic Python scorer that ranks and evicts
entries against a token budget.

API keys are read from environment variables or a project-root `.env` file:

| Provider    | Env var             |
| ----------- | ------------------- |
| `deepseek`  | `DEEPSEEK_API_KEY`  |
| `openai`    | `OPENAI_API_KEY`    |
| `anthropic` | `ANTHROPIC_API_KEY` |

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
- `observe` project skill — emits structured observations with 7 types
  (entity, schema, insight, dispute, boundary, constant, result)
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
sets `context_map.freeze_until` for `runtime.materializer_freeze_seconds`.
Pending events are left unprocessed during the freeze and are picked up after it
expires.

Map entries (`MapEntry` in `core/context_map/schema.py`) carry stable
8-character `entry_id` values, observation type, summary, source event IDs,
materialization count, cycle bounds, and a token estimate. Priority is
recomputed each cycle from configurable `priority_weights`, recency bonus, and
staleness penalty (see `cartographer:` in `harness.yaml`). Evictions are
auditable — `EvictionRecord` entries record the structured reason.

Context maps are keyed by corpus, using the configured project id. App startup
currently injects the `deverino:default` map when present; `search_documents`
emits document-retrieval events under `deverino:codebase`.

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

# Dashboards
uv run harness-poc dashboard summary
uv run harness-poc dashboard serve

# Cartographer calibration
uv run harness-poc cartographer calibrate --window-days 14
uv run harness-poc cartographer calibrate --apply

# ACDL inspection (parse .acdl spec files)
uv run harness-poc acdl inspect path/to/spec.acdl
```

## TUI Commands

`uv run harness-poc` starts the Textual chat interface. It streams model output,
shows tool progress separately from assistant text, and tracks session token
usage.

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
├── app_factory.py          # Runtime wiring into AppState
├── core/
│   ├── config.py           # YAML/.env config loading
│   ├── logging.py          # Logging configuration
│   ├── permissions.py      # Permission model
│   ├── events/             # Typed event hierarchy and async pub/sub
│   │   ├── events.py       # Event dataclasses and registry
│   │   ├── event_bus.py    # Sync/async pub/sub
│   │   ├── event_store.py  # Durable event persistence
│   │   ├── event_log_observer.py # Event log tailing
│   │   └── context_map_events.py # PEEK-style context-map event models
│   ├── acdl/               # ACDL parser and CLI app
│   │   └── cli.py          # `harness-poc acdl …` sub-commands
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
│   │   ├── dashboard.py    # Summary and live dashboard
│   │   └── logfire_subscriber.py # Logfire event forwarding
│   ├── processors/         # Async LLM, skill, and circuit-breaker workers
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
│   ├── skills/             # Skill discovery and execution
│   │   ├── skill_runner.py # SKILL.md discovery/execution
│   │   ├── skill_catalog.py # Skill registry
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
│       ├── tool_runner.py  # Tool discovery/execution
│       ├── tool_context.py # ToolContext type
│       └── tool_result.py  # ToolResult type
├── system_tools/           # Built-in LLM-callable primitives
│   ├── file_tools.py       # read_file, write_file, patch, search_files
│   ├── container_spawn.py, container_exec.py, container_destroy.py
│   ├── execute_python.py
│   ├── read_memory.py
│   ├── knowledge_tools.py
│   ├── acdl_tools.py       # acdl_inspect
│   └── inspect_context.py  # inspect_own_context
├── system_skills/          # System agent skills
└── system_prompts/         # SOUL.md primary system prompt

skills/                     # Project-local tools, skills, and knowledge skills
workflows/                  # YAML workflow definitions
pipelines/                  # YAML pipeline DAG definitions
personas/                   # Prompt templates for sub-agents
vespa/document_retrieval/   # Vespa app package for doc_chunk retrieval
```

## Runtime Model

The newer goal path is event-sourced:

```text
AgentInputAdded
  -> LLM worker emits LLMActionEmitted, SkillRequested, or LLMTextEmitted
  -> skill worker executes requested skills and emits SkillCompleted
  -> circuit breaker watches token/failure budgets and emits StreamPaused
```

Events are Pydantic models persisted through `EventStore` and published through
`EventBus`. Reducers derive session snapshots from durable events so workers can
rebuild state without holding private cross-loop mutable state.

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

The TUI and pipeline agent nodes still use the tested `GoalRunner` path for some
flows while the migration settles. `GoalRunner` includes semantic retry
detection, context-window compression, budget enforcement, and `evaluate_goal`
interception.

## Tools, Skills, And Knowledge

Deverino separates four kinds of callable/project knowledge:

- **Built-in tools** are pure primitives registered in `harness_poc/system_tools/`.
- **Tool skills** are `SKILL.md` packages with `type: tool`, often project-local
  in `skills/`.
- **Agent skills** are orchestration capabilities with `type: skill`; they may
  call LLMs, spawn sub-agents, or manage multi-step state.
- **Knowledge skills** are markdown instruction documents with `type: knowledge`;
  they are loaded on demand as context, not executed.

Selected built-in tools and project tools:

| Name                                                     | Purpose                                            |
| -------------------------------------------------------- | -------------------------------------------------- |
| `read_file`, `write_file`, `patch`, `search_files`       | Workspace file operations                          |
| `container_spawn`, `container_exec`, `container_destroy` | Docker/Podman sandbox management                   |
| `execute_python`                                         | Run Python in a session-scoped container           |
| `read_memory`                                            | Read blackboard memory                             |
| `web_search`                                             | LangSearch-backed web search                       |
| `semble_search`                                          | Semantic code search                               |
| `skills_list`, `skill_view`, `skill_manage`              | Discover and manage knowledge skills               |
| `append_event`                                           | Append typed context-map events                    |
| `observe`                                                | Record structural observations (7 types: entity, schema, insight, dispute, boundary, constant, result) for the context map |
| `context-map-materializer`                               | Materialize context-map events into a prompt cache |
| `index_documents`                                        | Feed project documents into Vespa                  |
| `search_documents`                                       | Search indexed Vespa chunks                        |
| `review_work`                                            | Review the current working tree                    |
| `inspect_own_context`                                    | Return the agent's own assembled system prompt for self-inspection |
| `acdl_inspect`                                           | Parse an ACDL spec file and return a structured summary |

Selected agent and knowledge skills:

| Name                | Purpose                                            |
| ------------------- | -------------------------------------------------- |
| `delegate_task`     | Spawn a persona-specific sub-agent                 |
| `evaluate_goal`     | Structured goal completion/blockage signal         |
| `consolidate_state` | Preview, propose, or approve state consolidation   |
| `summarize_memory`  | Summarize a blackboard memory key                  |
| `reflect_on_result` | Judge whether a result satisfies an objective      |
| `spec_writer`       | Gather requirements and draft implementation specs |
| `create_rubrics`     | Generate benchmark rubrics from behaviour descriptions |
| `paper-claim-verification` | Verify design-doc paper citations against indexed papers |
| `developer-pedagogy` | Project knowledge about developer preferences and constraints |
| `deverino-react-acdl` | ACDL description of the Deverino ReAct loop       |
| `acdl-syntax`        | ACDL grammar quickstart and gotchas               |
| `acdl-tooling`       | How to use `acdl_inspect` from inside the agent loop |
| `deterministic-cartographer` | Design rationale for the deterministic Cartographer migration |

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
included in telemetry.

```bash
export LOGFIRE_TOKEN=<your-token>
uv run harness-poc
```

## Development

```bash
uv run ruff check .    # lint
uv run ty check        # type check
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

Within each layer, tests are grouped by domain — e.g. `tests/` includes
subdirectories for `context_map/`, `retrieval/`, `runtime/`, `skills/`,
`processors/`, `repl/`, `event/`, `infra/`.

All fast tests in one go:

```bash
uv run pytest tests/unit/ tests/agent/
```

Benchmarks are opt-in (real LLM costs tokens):

```bash
just test-bench
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

## Container Sandbox

Container-backed tools use Docker or Podman. The default image is
`deverino-python:latest`, built from the project `Dockerfile` on first use if it
is not already available.

Change the default image in `harness.yaml`:

```yaml
runtime:
  default_container_image: deverino-python:latest
```
