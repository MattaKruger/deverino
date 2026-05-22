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
project:
  id: deverino

llm:
  provider: deepseek # deepseek | openai | anthropic
  model: deepseek-v4-pro

runtime:
  database_url: postgresql://deverino:deverino@localhost/deverino
  materializer_poll_interval: 30
  materializer_max_event_tokens: 8000
  materializer_token_budget: 1024
  materializer_freeze_threshold: 3
  materializer_freeze_seconds: 300

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
  -> context-map-materializer skill
  -> Distiller -> Cartographer -> Evictor
  -> compact context_map row
  -> next app/session prompt includes the stored map
```

Current context-map components:

- typed Pydantic event models in `harness_poc/core/context_map_events.py`
- PostgreSQL tables `context_map_events` and `context_map`
- `append_event` system skill for manually appending typed events
- `context-map-materializer` project skill for Distiller, Cartographer, and
  budget enforcement passes
- `MaterializerRunner`, started by the TUI and main async runtime, which polls
  pending corpus keys and materializes them in the background
- automatic `document_retrieved` and `search_failed` events from
  `search_documents`
- prompt injection of the stored context map during app-state creation

The materializer avoids repeated LLM calls when a corpus is stable. Each skill
run reports whether the persisted map actually changed; after
`runtime.materializer_freeze_threshold` consecutive no-change cycles, the runner
sets `context_map.freeze_until` for `runtime.materializer_freeze_seconds`.
Pending events are left unprocessed during the freeze and are picked up after it
expires.

Map entries also carry stable 8-character `entry_id` values in addition to their
human-readable slug keys. `ADD` creates a new ID, `REPLACE` keeps the existing ID,
and old map rows are normalized on the next materializer pass. Budget evictions
and upward section promotions append `map_entry_evicted` and
`map_entry_promoted` derivation events, including the affected `entry_id` when
available, so map evolution remains auditable.

Context maps are keyed by corpus, using the configured project id. App startup
currently injects the `deverino:default` map when present; `search_documents`
emits document-retrieval events under `deverino:codebase`. The manual event
skill accepts explicit corpus keys:

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
│   ├── context_map_events.py # PEEK-style context-map event models
│   ├── materializer_runner.py # Background context-map materializer poller
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

The context-map subsystem uses its own event log in the blackboard. Tool and
skill activity appends typed orientation events, and the background materializer
turns unprocessed events into a compact map that is loaded into future system
prompts. This map is a cache, not a source of truth; if materialization fails,
events remain unprocessed and are retried on a later poll.
Stable maps can be temporarily frozen to save materializer LLM calls, while new
events continue accumulating in the event log.

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
| `observe`                                                | Record structural observations for the context map |
| `context-map-materializer`                               | Materialize context-map events into a prompt cache |
| `index_documents`                                        | Feed project documents into Vespa                  |
| `search_documents`                                       | Search indexed Vespa chunks                        |
| `review_work`                                            | Review the current working tree                    |

Selected agent and knowledge skills:

| Name                | Purpose                                            |
| ------------------- | -------------------------------------------------- |
| `delegate_task`     | Spawn a persona-specific sub-agent                 |
| `evaluate_goal`     | Structured goal completion/blockage signal         |
| `consolidate_state` | Preview, propose, or approve state consolidation   |
| `summarize_memory`  | Summarize a blackboard memory key                  |
| `reflect_on_result` | Judge whether a result satisfies an objective      |
| `spec_writer`       | Gather requirements and draft implementation specs |
| `paper-claim-verification` | Verify design-doc paper citations against indexed papers |
| `developer-pedagogy` | Project knowledge about developer preferences and constraints |
| `deverino-react-acdl` | ACDL description of the Deverino ReAct loop       |

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
│ 88 tests │     │ 12 tests │     │  1 test  │
│  ~0.2s   │     │  ~1.6s   │     │ real LLM │
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

All fast tests in one go:

```bash
uv run pytest tests/unit/ tests/agent/
```

### Layer rules

| If a test imports... | It belongs in |
|---------------------|---------------|
| Nothing from `harness_poc` (pure function) | `unit/` |
| `BlackboardDatabase` or `in_memory_engine` fixture | `unit/` |
| `SessionHarness` | `agent/` |
| `AppState` or `build_app_state` | `agent/` or `bench/` |
| Real `build_model()` with API keys | `bench/` |

### Unit tests (`tests/unit/`)

Test one thing. No harness, no real LLM, no Postgres. In-memory SQLite for
database-dependent tests.

**Example — testing a database operation:**

```python
# tests/unit/test_database_core.py

def test_write_and_read_memory_string(in_memory_engine):
    """Write a string, read it back. Session isolation works."""
    db = BlackboardDatabase(in_memory_engine)
    sid = db.start_session("test")

    db.write_memory(sid, "greeting", "hello")
    result = db.read_memory(sid, "greeting")

    assert result == "hello"
```

**Example — testing a pure function:**

```python
# tests/unit/test_events.py

def test_skill_completed_populates_tool_name_from_skill_name():
    """When only skill_name is set, tool_name is auto-populated."""
    event = SkillCompleted(
        session_id="s1",
        skill_name="read_memory",
        status="success",
        content="done",
    )
    assert event.tool_name == "read_memory"
```

No fixtures needed for pure functions. Use `in_memory_engine` fixture
(defined in `tests/conftest.py`) for database tests.

### Agent tests (`tests/agent/`)

Test the GoalRunner loop. A mock LLM returns predetermined responses — no API
calls. Skills execute against an in-memory database. The test defines a
sequence of LLM actions and asserts what the loop did with them.

**Core concept:** `SessionHarness.build([response, response, ...])` — each
element is what the mock LLM returns for one iteration of the goal loop.

Three factory functions produce mock responses:

```python
from tests.helpers import (
    tool_call_response,        # model calls a skill
    evaluate_goal_response,    # model says the goal is complete (or not)
    text_response,             # model emits text without calling a tool
    skill_result,              # mock what a skill returns (for skill_overrides)
)
```

**Example — the simplest agent test:**

```python
# tests/agent/test_goal_loop.py

def test_completes_on_direct_evaluate_goal():
    """Model immediately evaluates the goal as complete."""
    harness = SessionHarness.build([
        evaluate_goal_response(True, "Nothing to do.", "All good."),
    ])

    harness.run("check status")

    harness.assert_completed()
    harness.assert_final_answer_contains("All good")
```

**Example — a two-skill chain with data dependency:**

```python
def test_reads_memory_then_evaluates():
    """Model reads from the blackboard, then evaluates complete."""
    harness = SessionHarness.build([
        tool_call_response("read_memory", {"memory_key": "context_summary"}),
        evaluate_goal_response(True, "Read complete.", "Project has 3 sessions."),
    ])

    # Pre-seed data the real skill will read.
    harness.state.database.write_memory(
        harness.state.session_id,
        "context_summary",
        "Project has 3 active sessions and 12 stored memory keys.",
    )

    harness.run("summarise the project state")

    harness.assert_skill_called("read_memory")
    harness.assert_skill_completed("read_memory", status="success")
    harness.assert_completed()
```

**Mocking external skills:**

Skills that need external services (Vespa, web, subprocess) can be overridden
with `skill_result()`. The mock result is returned instead of executing the
real skill.

```python
def test_recovers_from_failed_search_by_reading_memory():
    harness = SessionHarness.build(
        [
            tool_call_response("search_documents", {"query": "architecture"}),
            tool_call_response("read_memory", {"memory_key": "architecture_notes"}),
            evaluate_goal_response(True, "Found in memory.", "Three layers."),
        ],
        skill_overrides={
            "search_documents": skill_result(
                status="failed",
                content="Vespa connection refused.",
            ),
        },
    )
    # Pre-seed data, run, assert...
```

**Available assertions:**

| Method | What it checks |
|--------|---------------|
| `assert_completed()` | GoalRunResult.status == "completed" |
| `assert_budget_exhausted()` | GoalRunResult.status == "budget_exhausted" |
| `assert_skill_called(name)` | A SkillCalled event exists for this skill |
| `assert_skill_not_called(name)` | No SkillCalled event exists for this skill |
| `assert_skill_completed(name, status=)` | A SkillCompleted event exists with this status |
| `assert_skill_order("a", "b", ...)` | Skills were called in this relative order |
| `assert_final_answer_contains(fragment)` | Result content contains this text (case-insensitive) |

**Important:** `evaluate_goal` is intercepted by GoalRunner — it emits a
`GoalEvaluated` event, not a `SkillCalled` event. Do not include it in
`assert_skill_order()` or in a rubric's `skill_sequence`.

### Benchmark tests (`tests/bench/`)

Test agent output quality with a real LLM. Opt-in via `--run-benchmarks`.
Each benchmark is paired with a rubric — a `.md` file that defines hard gates
(free, deterministic) and an LLM judge (token cost).

**Running benchmarks:**

```bash
just test-bench                           # default: haiku
just test-bench claude-sonnet-4-6         # cross-model comparison
```

**Rubric format (`tests/bench/rubrics/<slug>.md`):**

```markdown
# Rubric: summarise-blackboard-database

## Goal

Summarise what BlackboardDatabase does and how it is structured.

## Hard Assertions

- must_contain: "session"
- must_contain: "SQLite"
- must_not_contain: "I don't know"
- min_words: 50
- skill_sequence: [read_memory]

## LLM Judge

threshold: 0.7
model: claude-haiku-4-5-20251001
prompt: |
  Score 0.0-1.0: does the answer accurately describe
  the BlackboardDatabase's purpose and structure?

  Answer: {answer}
```

**Hard gates** run first — they're free and fail-fast. **LLM judge** only
fires if hard gates pass — saves tokens on clearly wrong answers.

**Benchmark test structure:**

```python
@pytest.mark.benchmark
def test_summarise_blackboard_database(live_session, rubric):
    result = live_session.run(rubric.goal)
    rubric.assert_hard_gates(result, events=live_session.events)
    score = rubric.judge(result.content, config=live_session.state.config.llm)
    assert score >= rubric.judge_threshold
```

The `live_session` fixture wires a real LLM via `BENCHMARK_MODEL` env var.
The `rubric` fixture loads the `.md` file by convention:
`test_summarise_blackboard_database` → `summarise-blackboard-database.md`.

### Writing a new test

**Unit test** — create `tests/unit/test_<thing>.py`:

1. Add `# ruff: noqa: ANN201, FBT003` at the top
2. Use `in_memory_engine` fixture if you need a database
3. No imports from `harness_poc.app_factory` — that's an agent/bench concern

**Agent test** — add to `tests/agent/test_skill_chains.py` (or create a new file):

1. Import `SessionHarness` from `tests.agent.harness`
2. Import factories from `tests.helpers`
3. Build a mock response sequence — each element is one loop iteration
4. Pre-seed data with `harness.state.database.write_memory()` if real skills need it
5. Override external skills with `skill_overrides` if they'd need real services
6. `harness.run(goal)` then assert

**Benchmark test** — create `tests/bench/test_<thing>.py` and a matching rubric:

1. Write the rubric `.md` file first — define what "good" looks like
2. Create the test function using `live_session` and `rubric` fixtures
3. Add `@pytest.mark.benchmark` decorator
4. Run with `--run-benchmarks`

### Design decisions

| Decision | Why |
|----------|-----|
| In-memory SQLite for agent tests | No Postgres drift. Same construction path via `database_url`. |
| Manual `SessionHarness.build()` — no auto-fixture | The mock response sequence IS the test. It belongs inline. |
| `RecordingEventBus` instead of real `EventBus` | No persistence, no subscribers. Tests read events directly. |
| `skill_overrides` dict on `SessionHarness.build()` | Mock only the skills that need external services. Real skills still execute. |
| Rubrics as `.md` files | Readable as documentation. Parseable as structured data. Same file validates both mock and live sessions. |
| LLM judge uses a cheap model (haiku) | Scoring doesn't need reasoning depth. Keeps benchmark costs predictable. |
| `--run-benchmarks` opt-in flag | Prevents accidental token spend during normal test runs. |

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
