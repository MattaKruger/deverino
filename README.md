# Deverino

Deverino is a Python 3.12 proof-of-concept LLM agent harness. It combines a
Textual chat TUI, a Typer CLI, an event-sourced async runtime, project-local
skills, declarative workflows and pipelines, PostgreSQL-backed state, and
Vespa-backed document retrieval.

The project is intentionally experimental, but the runtime pieces are concrete:
agents and tools communicate through typed durable events, skills use explicit
permission metadata, and document search returns cited chunks from a Vespa
schema built for hybrid retrieval.

## Quickstart

Start the local backing services:

```bash
docker compose up -d postgres vespa
docker compose exec vespa vespa deploy /vespa-app
```

Vespa can take a short time to become ready before deployment succeeds. The
application package lives in `vespa/document_retrieval/` and is mounted into the
container at `/vespa-app`.

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
llm:
  provider: deepseek # deepseek | openai | anthropic
  model: deepseek-v4-flash

runtime:
  database_url: postgresql://deverino:deverino@localhost/deverino

retrieval:
  enabled: true
  provider: vespa
  vespa_url: http://localhost:8080
  namespace: deverino
  schema: doc_chunk
  default_hits: 8
  default_mode: hybrid
```

API keys are read from environment variables or a project-root `.env` file:

| Provider | Env var |
| --- | --- |
| `deepseek` | `DEEPSEEK_API_KEY` |
| `openai` | `OPENAI_API_KEY` |
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
uv run harness-poc documents index docs/example.pdf
```

Index a directory of PDFs:

```bash
uv run harness-poc documents index docs --glob "*.pdf"
```

Force reindexing even when content hashes have not changed:

```bash
uv run harness-poc documents index docs/example.pdf --force
```

From the TUI, ask the agent to use retrieval skills directly:

```text
Use index_documents with {"paths":["docs", "README.md"]}
Use search_documents with {"query":"state consolidation proposals","mode":"hybrid","hits":5}
```

Search results are formatted as cited chunks such as `docs/example.md#chunk-2`.

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
uv run harness-poc documents index docs/example.pdf
uv run harness-poc documents index docs --glob "*.md" --force

# Skills and tools
uv run harness-poc skill list
uv run harness-poc skill show index_documents
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
│   ├── database.py         # PostgreSQL blackboard and metadata access
│   ├── db_engine.py        # SQLAlchemy engine setup
│   ├── events.py           # Typed event hierarchy and registry
│   ├── event_store.py      # Durable event persistence
│   ├── event_bus.py        # Sync/async event publication and subscriptions
│   ├── reducers.py         # Snapshot derivation from event history
│   ├── processors/         # Async LLM, skill, and circuit-breaker workers
│   ├── pydantic_runtime.py # PydanticAI streaming/tool runtime
│   ├── pipeline_runner.py  # Wave-based DAG execution
│   ├── workflow_runner.py  # YAML workflow execution
│   ├── retrieval.py        # Retrieval domain models and chunking
│   ├── document_index.py   # File/PDF indexing into retrieval chunks
│   ├── vespa_client.py     # pyvespa adapter
│   ├── skill_runner.py     # SKILL.md discovery/execution
│   └── tool_runner.py      # Built-in tool discovery/execution
├── system_tools/           # Built-in LLM-callable primitives
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

Common built-in tools and project tools:

| Name | Purpose |
| --- | --- |
| `read_file`, `write_file`, `patch`, `search_files` | Workspace file operations |
| `container_spawn`, `container_exec`, `container_destroy` | Docker/Podman sandbox management |
| `execute_python` | Run Python in a session-scoped container |
| `read_memory` | Read blackboard memory |
| `web_search` | LangSearch-backed web search |
| `semble_search` | Semantic code search |
| `index_documents` | Feed project documents into Vespa |
| `search_documents` | Search indexed Vespa chunks |
| `review_work` | Review the current working tree |

Common agent skills:

| Name | Purpose |
| --- | --- |
| `delegate_task` | Spawn a persona-specific sub-agent |
| `evaluate_goal` | Structured goal completion/blockage signal |
| `consolidate_state` | Preview, propose, or approve state consolidation |
| `summarize_memory` | Summarize a blackboard memory key |
| `reflect_on_result` | Judge whether a result satisfies an objective |
| `spec_writer` | Gather requirements and draft implementation specs |

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
uv run pytest
uv run ruff check .
uv run ty check

uv run pytest tests/test_document_index.py -v
uv run pytest tests/test_vespa_client.py tests/test_search_documents.py -v
uv run pytest tests/test_event_bus.py tests/test_event_store.py -v
```

Live Vespa integration tests are opt-in:

```bash
VESPA_INTEGRATION=1 uv run pytest tests/test_vespa_integration.py -v
```

Recent full-suite baseline during this README update: `311 passed, 5 skipped`.

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
