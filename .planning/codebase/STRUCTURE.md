---
title: Deverino Repository Structure Map
mapped_at: 2026-07-11
last_mapped_commit: cf99f7e
focus: structure
---

# Repository Structure

## Top-Level Layout

```text
deverino/
├── harness_poc/              Python application package
├── dashboard-ui/             Vue dashboard and AG-UI chat client
├── skills/                   Project-local executable and knowledge skills
├── harness_poc/system_skills Built-in executable skills shipped with the package
├── harness_poc/system_tools  Code-native tools registered for model calls
├── workflows/                Sequential skill state-machine definitions
├── pipelines/                DAG skill/agent pipeline definitions
├── personas/                 Persona prompt documents
├── subagents/                Persona-specific sub-agent tool/permission config
├── agents/roles/             Additional role skill assets
├── vespa/                    Vespa document-retrieval application package
├── tests/                    Main pytest suite, grouped by capability
├── evals/                    Evaluation tasks, baselines, and generated results
├── docs/                     Architecture, plans, research, guides, and papers
├── specs/ and plans/         Older implementation specifications and plans
├── scripts/                  Maintenance, paper retrieval, OCR, skill compilation
├── acdl-visualizer/           Standalone ACDL visualization assets
├── deverino_react.acdl        Active ReAct/system-prompt composition specification
├── harness.yaml              Runtime, model, retrieval, and path configuration
├── pyproject.toml             Python package, dependencies, lint, and test config
├── docker-compose.yml         Local PostgreSQL/Vespa service composition
└── Justfile                   Common development commands
```

`.planning/codebase/` contains generated codebase-intelligence documents. `.harness/`,
`.deverino-scratch/`, `.cache/`, `.pytest_cache/`, `.ruff_cache/`, `.uv-cache/`, `tmp/`,
`dashboard-ui/node_modules/`, `dashboard-ui/dist/`, and `site/` are runtime, cache, build, or
generated documentation outputs rather than source ownership boundaries.

## Python Package

### Surface and Composition Files

| Path | Ownership |
|---|---|
| `harness_poc/main.py` | Package-script entrypoint; delegates to Typer. |
| `harness_poc/cli.py` | Typer root and subcommands for REPL, goal, events, state, skills, tools, documents, pipelines, dashboard, cartographer, v2, and evals. |
| `harness_poc/repl.py` | Interactive input routing, slash commands, chat/v2 mode handling, token/message persistence. |
| `harness_poc/repl_completion.py` | Prompt-toolkit completion for REPL commands and resources. |
| `harness_poc/tui.py` | Textual application, panels, key bindings, run control, and bridge to REPL handlers. |
| `harness_poc/tui_vim.py` | Optional Vim-style input behavior for the TUI. |
| `harness_poc/app_factory.py` | Composition root and system-prompt assembly. |
| `harness_poc/console.py` | Shared Rich console output helpers. |
| `harness_poc/dashboard_theme.py` | Dashboard/TUI presentation constants. |

Changes that alter application wiring or cross-cutting runtime dependencies belong in
`app_factory.py`; user command behavior belongs in `cli.py`/`repl.py`; model execution internals
belong under `core/runtime/`.

### `harness_poc/core/`

`core/` is the shared runtime and infrastructure package. V2 imports it directly.

| Directory | Ownership | Key files |
|---|---|---|
| `core/acdl/` | Parse ACDL and assemble/execute its prompt/control graph. | `ast.py`, `parser.py`, `executor.py`, `cli.py` |
| `core/ahe/` | Autonomous harness evolution telemetry, diagnosis, and proposal logic. | `telemetry.py`, `diagnose.py`, `propose.py` |
| `core/context_map/` | Observation schema, LLM distillation, deterministic projection, ranking/budget policy, calibration, and rendering. | `schema.py`, `distiller.py`, `cartographer.py`, `render.py`, `config.py`, `sections.py`, `copt_gate.py` |
| `core/eval/` | Evaluation task loading, judging, refinement, and run orchestration. | `task.py`, `judge.py`, `refine.py`, `runner.py` |
| `core/events/` | Typed session/context events, persist-before-dispatch bus, event store, and log reads. | `events.py`, `context_map_events.py`, `event_bus.py`, `event_store.py` |
| `core/execution/` | Polling context materializer, sequential workflows, and DAG pipelines. | `materializer_runner.py`, `workflow_runner.py`, `pipeline_runner.py` |
| `core/observability/` | Dashboard query/read models and Logfire subscriber integration. | `dashboard.py`, `logfire_subscriber.py` |
| `core/observe/` | Internal timing, trace, and logging tap primitives. | `trace.py`, `timing.py`, `log_tap.py` |
| `core/processors/` | Core async event-loop workers and their supervisor. | `llm_worker.py`, `tool_worker.py`, `circuit_breaker.py`, `processor_supervisor.py` |
| `core/retrieval/` | Document conversion, chunking, embeddings, Vespa indexing/search. | `document_index.py`, `pdf_converter.py`, `embedder.py`, `vespa_client.py`, `retrieval.py` |
| `core/runtime/` | PydanticAI model/agent runtime, iterative goals, history, reducers, token accounting. | `pydantic_runtime.py`, `goal_runner.py`, `message_history.py`, `reducers.py` |
| `core/skills/` | Skill discovery, frontmatter parsing, compilation, execution context, permissions, catalog, scaffolding. | `skill_runner.py`, `skill_compiler.py`, `skill_context.py`, `skill_bundle.py` |
| `core/storage/` | SQLModel schema, engine, broad blackboard facade, state types, permission proxy. | `models.py`, `database.py`, `db_engine.py`, `state.py`, `blackboard_proxy.py` |
| `core/tools/` | Built-in tool discovery/execution, contexts/results, and guard chain. | `tool_runner.py`, `guards.py`, `tool_context.py` |

Cross-cutting configuration belongs in `core/config.py`; logging bootstrap belongs in
`core/logging.py`; workspace/blackboard permission values belong in `core/permissions.py`.

### `harness_poc/v2/`

V2 is organized by orchestration role rather than by infrastructure:

| Path | Ownership |
|---|---|
| `v2/wiring.py` | Builds mode-specific runtime containers and adapters over core services. |
| `v2/context_engine.py` | Persona/pedagogy/verified-state context assembly and failure warm-up. |
| `v2/execution_engine.py` | Foreground/background sub-agent execution and deterministic test gate. |
| `v2/workflow_orchestrator.py` | Probe -> execute -> gate workflow, imperative and bus-driven. |
| `v2/agent_config.py` | Loads sub-agent tool and permission definitions. |
| `v2/contracts/` | Protocols and data contracts for event runtime, context materialization, and sub-agent spawning. |
| `v2/handlers/` | Command handlers such as delegated-task execution and blackboard writes. |
| `v2/subscribers/` | ReAct and pipeline event subscribers. |
| `v2/tests/` | Co-located v2 tests retained separately from the main test tree. |

V2 does not own storage or a separate bus. New v2 behavior should use the core typed events and
the `Identity` dependencies passed by `v2/wiring.py`.

### Built-In Extension Surfaces

`harness_poc/system_skills/<name>/` contains packaged skills. Each directory normally has
`SKILL.md`, `__init__.py`, `skill.py`, and a generated `.skill_bundle.json`.

`harness_poc/system_tools/*.py` contains code-native tool modules. Importing a module registers its
handler in `harness_poc/system_tools/__init__.py`; `ToolRunner` discovers these lazily.

`harness_poc/system_prompts/` owns SOUL prompt assets. The compact file is preferred by
`app_factory._resolve_soul_prompt()` when configured and present.

## Project-Level Extension Assets

### Skills

`skills/<name>/SKILL.md` is authoritative metadata/instruction content. Executable skills add
`skill.py` and `__init__.py`; knowledge-only skills may contain only `SKILL.md`. The notable
context projection adapter is `skills/context-map-materializer/skill.py`, which coordinates the
core distiller, cartographer, CopT gates, and database commit.

### Workflows and Pipelines

`workflows/*.yaml` defines named sequential states consumed by `WorkflowRunner`. State arguments
can interpolate inputs and earlier results; states may read project state or append session state.

`pipelines/*.yaml` defines DAG nodes consumed by `PipelineRunner`. Nodes are `skill` or `agent`,
dependencies determine execution waves, and independent nodes may run concurrently.

### Personas and Sub-Agents

`personas/*.md` contains role prompts. `subagents/*.yml` selects tools and permissions for those
roles. `agents/roles/` holds additional role-scoped skill content and is not the primary runtime
persona lookup path.

## API and Frontend

### FastAPI

| Path | Ownership |
|---|---|
| `harness_poc/api/__init__.py` | FastAPI factory, database engine, CORS, route registration, compiler-model preload. |
| `harness_poc/api/routes.py` | Dashboard reads, event SSE, skill compilation, project-state endpoints. |
| `harness_poc/api/chat.py` | Chat-session CRUD, AG-UI SSE execution, cancellation, runtime cache. |

The API receives the database engine through `app.state`. Chat runtime/config/model caches also
live on application state; they are not persisted service objects.

### Vue Dashboard

| Directory | Ownership |
|---|---|
| `dashboard-ui/src/views/` | Route-level Overview, Context Map, Sessions, Session Detail, Sub-Agents, Tokens, Skills, State, and Chat screens. |
| `dashboard-ui/src/components/` | Domain and shared display components. |
| `dashboard-ui/src/stores/` | Pinia stores; most use polling via `composables.ts`. |
| `dashboard-ui/src/api/` | HTTP client, typed endpoint wrappers, event SSE, compilation SSE. |
| `dashboard-ui/src/types/` | Dashboard transport/view types. |
| `dashboard-ui/src/router.ts` | Browser route ownership. |

`dashboard-ui/vite.config.ts`, `tsconfig.json`, `tailwind.config.ts`, and `package.json` own the
frontend build. `dashboard-ui/dist/` is generated output.

## Data and Infrastructure

`harness.yaml` is the runtime source of configuration for project identity, database URL, model,
materializer policy, paths, retrieval, observability, compiler, and TUI behavior. Environment
variables provide credentials/provider overrides through Pydantic settings.

`docker-compose.yml` and `Dockerfile` support local/runtime infrastructure. Vespa deployment files
live under `vespa/document_retrieval/`; PostgreSQL schemas are created by SQLModel and targeted
raw migrations inside `BlackboardDatabase.create_tables()`.

`docs/` is descriptive material, not runtime input except when configured as a retrieval corpus.
`docs/superpowers/specs/` contains current design specifications; `specs/`, `plans/`, and
`docs/archive/` contain older or feature-specific planning artifacts.

## Tests

The primary tests are under `tests/`, grouped by `agent`, `bench`, `cli`, `context_map`, `event`,
`infra`, `pressure`, `processors`, `repl`, `retrieval`, `runtime`, `skills`, `storage`,
`system_tools`, and `unit`. Root-level `tests/test_*.py` cover cross-cutting flows. V2 retains a
second co-located suite in `harness_poc/v2/tests/`.

Place focused tests beside the owning capability in `tests/<capability>/`; use
`harness_poc/v2/tests/` only when extending the existing v2-local suite. Integration tests that
need PostgreSQL or Vespa use the `integration` marker; live quality runs use `benchmark`.

## Placement Rules for Refactoring

- Typed event envelopes and bus/store mechanics belong in `core/events/`, not in a UI or v2 engine.
- Context observation/projection domain types and pure policy belong in `core/context_map/`.
- PostgreSQL implementations belong in `core/storage/`; avoid adding persistence to skills.
- Trigger policy and long-running workers belong in `core/execution/` or the host composition root.
- Model-specific distillation belongs behind the context-map domain boundary, currently
  `core/context_map/distiller.py`.
- CLI/TUI/API files should translate user input and render output; orchestration belongs below
  those surfaces.
- V2 code should adapt/reuse core capabilities rather than duplicate event, storage, or tool
  infrastructure.
