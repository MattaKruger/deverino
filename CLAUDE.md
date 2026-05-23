# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
uv run harness-poc              # start interactive REPL (prompt-toolkit)
uv run harness-poc tui          # start Textual TUI (ChatApp)
uv run harness-poc --help       # list CLI sub-commands

# Skills
uv run harness-poc skill list                         # discover system + project skills
uv run harness-poc skill show <name>                  # show skill metadata

# State
uv run harness-poc state show project                 # print durable project state
uv run harness-poc state propose <key> <value>        # propose a state change
uv run harness-poc state approve <proposal_id>        # approve a proposal

# Workflows
uv run harness-poc workflow run <name> "<objective>"  # execute a workflow

# Pipelines (DAG-style)
uv run harness-poc pipeline list                      # list available pipelines
uv run harness-poc pipeline run <name> "<objective>"  # execute a pipeline

# Documents / retrieval
uv run harness-poc documents index <path>             # index documents into Vespa

# Testing & quality
uv run pytest                          # full test suite
uv run pytest tests/test_goal_runner.py  # focused single file
uv run ruff check .                    # lint (line-length=100, double quotes)
uv run ty check                        # static type checks
```

A `Justfile` at the repo root wraps common recipes: `just repl`, `just tui`, `just test`, `just lint`, `just types`.

## Architecture

**Deverino** is a Python 3.14 proof-of-concept for autonomous LLM agent workflows backed by PostgreSQL (SQLite in tests).

### Skill system

Each skill is a self-contained directory with `SKILL.md` (metadata: name, description, args schema) and `skill.py` (an `execute(ctx: SkillContext) -> SkillResult` function). Skills are discovered at startup by `core/skills/skill_runner.py` scanning `harness_poc/system_skills/` and the project-local `skills/` directory. They are registered as OpenAI tool-call definitions so the LLM can invoke them.

**System skills** (built into the harness):
- `delegate_task` — spawns a sub-agent for a subtask
- `consolidate_state` — drives the two-step state-promotion flow (session → project state)
- `evaluate_goal` — intercept point for GoalRunner loop termination; when called outside a goal run it is a stub
- `read_memory` — reads from the blackboard shared memory

**Project skills** (repo-local, user-defined in `skills/`):
- `reflect_on_result`, `review_work`, `spec_writer`, `summarize_memory` — core reasoning skills
- `index_documents`, `search_documents` — document ingestion and retrieval (backed by Vespa)
- `web_search` — external web search
- `semble_search` — Semble-specific retrieval
- `developer-pedagogy`, `deverino-test-knowledge` — domain-specific skills

### System tools

System tools live in `harness_poc/system_tools/` and are registered via an `@register` decorator in `__init__.py`. Unlike skills, they are invoked by the harness directly (not as LLM tool calls) and are not exposed in `skill list`.

- `container_spawn`, `container_exec`, `container_destroy` — Docker container lifecycle
- `execute_python` — run Python code in a subprocess
- `file_tools` — file system operations
- `knowledge_tools` — document source management (wraps Vespa indexing)
- `read_memory` — low-level blackboard read (mirrors the system skill)

Container tools mount `/workspace:ro` (read-only) and `/scratch:rw` (session-scoped writable). `TMPDIR`, `HOME`, `PYTHONPYCACHEPREFIX` are set to `/scratch` — writes to `/workspace` produce "Read-only file system" errors.

### Workflow runtime

`core/execution/workflow_runner.py` executes YAML files from `workflows/`. Each workflow is a **linear sequence** of states; each state specifies a skill name and argument templates (using `{{variable}}` substitution). The runner loops through states, calls the skill, and passes output forward.

### Pipeline runtime (DAG-style)

`core/execution/pipeline_runner.py` executes YAML files from `pipelines/`. Unlike workflows, pipelines are **DAGs**: nodes declare `depends_on` lists and independent nodes run in parallel via `ThreadPoolExecutor`. Each node can be a skill call or a `GoalRunner` invocation. Outputs flow between nodes via template substitution. Pipeline events (`PipelineStarted`, `PipelineNodeStarted`, `PipelineNodeCompleted`, `PipelineCompleted`) are emitted to the event bus.

### Event-driven processing

The runtime is event-driven. `core/events/events.py` defines typed event dataclasses (`LLMTextEmitted`, `LLMActionEmitted`, `SkillCompleted`, `AgentInputAdded`, `StreamPaused`, `PipelineStarted`, …). Three async processors handle the event loop:

- `core/processors/llm_worker.py` — drives LLM streaming and tool dispatch
- `core/processors/tool_worker.py` — executes skills and writes results back
- `core/processors/circuit_breaker.py` — catches unhandled exceptions, emits error events

`core/events/event_store.py` persists events; `core/events/event_bus.py` provides async pub/sub between processors.

### Blackboard (PostgreSQL / SQLite state)

`core/storage/database.py` (`BlackboardDatabase`) is constructed via `BlackboardDatabase.from_url(database_url)`. `harness.yaml` defaults to `postgresql://deverino:deverino@localhost/deverino`; tests fall back to `sqlite:///...`. It has seven tables:

| Table | Purpose |
|---|---|
| `sessions` | Per-run session records |
| `shared_memory` | Key-value LLM-written memory |
| `project_state` | Durable cross-session project facts |
| `session_state` | Ephemeral per-session facts |
| `state_proposals` | Proposed promotions from session → project state |
| `state_events` | Append-only event log (scope/scope_id/event_type/payload) |
| `session_snapshots` | Compressed state snapshots for context window management |
| `document_sources` | Indexed document metadata (URI, kind, status, hash) |
| `document_chunks` | Per-chunk Vespa IDs for indexed documents |

State promotion is a two-step process: a skill proposes a change (`state_proposals`), which must be approved before it is merged into `project_state`. The `consolidate_state` system skill drives this.

### Document retrieval (Vespa)

`core/retrieval/vespa_client.py` wraps a Vespa instance (configured in `harness.yaml` under `retrieval`). `index_documents` and `search_documents` project skills use `knowledge_tools` (system tool) to feed documents into Vespa and query them. `docker-compose.yml` runs Vespa locally.

### AppState & wiring

`app_factory.py` constructs the `AppState` dataclass that is threaded through every command, the REPL, and the TUI. It wires together: `HarnessConfig` (from `harness.yaml`), `BlackboardDatabase`, `LLMClient`, `SkillRunner`, `ToolRunner`, discovered skills, loaded workflows, and loaded pipelines.

### LLM runtime

`core/runtime/pydantic_runtime.py` (`PydanticAgentRuntime`) manages streaming agent execution with tool support. Uses `agent.iter()` (full-graph iterator) instead of `agent.run_stream()`. `GoalRunner` (`core/runtime/goal_runner.py`) runs the autonomous ReAct loop — async internally with `await agent.run()`, semantic stuck detection (normalized argument comparison against failed actions), and context window compression (Summarizer + sliding window with 8000-char budget). `GoalRunner` intercepts `evaluate_goal` tool calls to decide loop termination.

### REPL & TUI

`repl.py` uses `prompt-toolkit` to provide tab-completion over skill names, workflow names, pipeline names, and commands. It runs a message loop that feeds user input to the LLM client.

`tui.py` (`ChatApp`) is a full Textual TUI alternative with markdown rendering, file-path linkification, token count display, animated spinner, and auto-completion. Launch with `uv run harness-poc tui`.

### Configuration

`harness.yaml` at the repo root is the primary config file. `core/config.py` (`HarnessConfig`) loads it via `pydantic-settings`. Provider credentials (API keys) must come from environment variables — never from config files.

## Key conventions

- Ruff: `line-length = 100`, double quotes, `S101` ignored under `tests/`.
- Prefer typed functions and existing harness abstractions (`SkillContext`, `SkillResult`, `BlackboardDatabase`) over ad hoc parsing.
- Tests must be deterministic; avoid real network or model calls unless the test explicitly requires it.
- `blackboard.db` is local runtime state — do not commit it.
- `AGENTS.md` contains commit and PR guidelines; follow conventional imperative commit messages.
