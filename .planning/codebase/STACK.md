---
title: Technology Stack
mapped_at: 2026-07-11
last_mapped_commit: cf99f7e
focus: tech
---

# Technology Stack

## Runtime Surfaces

- The primary application is a Python 3.14 package under `harness_poc/`, installed and run with `uv`.
- `harness_poc/main.py` exposes the `harness-poc` console entry point declared in `pyproject.toml`.
- `harness_poc/cli.py` uses Typer for commands; `harness_poc/tui.py` uses Textual for the interactive chat UI.
- `harness_poc/app_factory.py` composes storage, event runtime, tools, skills, workflows, retrieval, and long-lived processors into `AppState`.
- `harness_poc/api/` is a FastAPI application served by Uvicorn for dashboard and chat HTTP/SSE endpoints.
- `dashboard-ui/` is a separate Vue 3 and TypeScript application built with Vite and pnpm.
- `acdl-visualizer/` is a standalone browser-side JavaScript/CSS visualizer; it is not part of the Vue build.

## Python Stack

- Packaging: Hatchling, configured in `pyproject.toml`; the wheel contains `harness_poc`.
- CLI and terminal UI: Typer, Rich, Textual, and Prompt Toolkit.
- Agent/model runtime: PydanticAI plus provider-specific model classes in `harness_poc/core/runtime/pydantic_runtime.py`.
- Configuration and schemas: dataclasses, Pydantic, Pydantic Settings, and PyYAML; project configuration lives in `harness.yaml`.
- Persistence: SQLModel over SQLAlchemy, `psycopg2-binary` for PostgreSQL, and `pgvector` for vector columns.
- Eventing: typed Pydantic events and an in-process async `EventBus` under `harness_poc/core/events/`; durable events are stored through the blackboard database.
- Retrieval: PyVespa, Sentence Transformers, NumPy, Docling, Docling Core, PyMuPDF, and tiktoken.
- Analysis/evaluation utilities: Polars, Matplotlib, and NetworkX.
- HTTP server/client: FastAPI, Uvicorn, and HTTPX; some scripts and OCR calls use stdlib `urllib`.
- Observability: standard-library logging plus optional Logfire/PydanticAI instrumentation.

## Frontend Stack

- `dashboard-ui/package.json` defines Vue 3.5, Vue Router 4, Pinia 2, and VueUse 11.
- Presentation dependencies are Tailwind CSS 4, ECharts 5 with `vue-echarts`, Splitpanes, Marked, and TDesign Vue Next Chat.
- Development/build tooling is Vite 6, TypeScript 5, Vue TSC 2, and pnpm.
- `dashboard-ui/vite.config.ts` aliases `@` to `dashboard-ui/src` and proxies `/api` to `http://127.0.0.1:8050`.
- The frontend consumes JSON endpoints and Server-Sent Events from `harness_poc/api/`; it is not served by FastAPI in the current development setup.

## Data Stores

- PostgreSQL is the authoritative runtime blackboard configured at `runtime.database_url` in `harness.yaml`.
- The checked-in default is `postgresql://deverino:deverino@localhost/deverino`; tests use the isolated service on port 5433.
- `harness_poc/core/storage/models.py` defines sessions, message history, shared memory, project/session state, state proposals/events, context-map events/views/cycles, document metadata, and v2 materialized context maps.
- PostgreSQL uses JSONB where available; `harness_poc/core/storage/db_engine.py` also supports SQLite with JSON, foreign keys, and WAL for lightweight tests.
- The CopT similarity gate stores embeddings in a PostgreSQL-only raw SQL table because pgvector is outside SQLModel metadata.
- Vespa is the retrieval index. PostgreSQL retains source/chunk metadata while Vespa stores searchable chunk text and 1024-dimensional embeddings.
- `vespa/document_retrieval/schemas/doc_chunk.sd` provides keyword, semantic, and hybrid rank profiles over BM25 and angular vector closeness.

## Models and Tokenization

- Current chat configuration in `harness.yaml` is GLM `glm-5.2` through an OpenAI-compatible BigModel endpoint.
- Supported model providers are GLM, OpenAI, Anthropic, and DeepSeek; missing credentials fall back to PydanticAI `TestModel`.
- Context distillation is separately configured as `glm/glm-5.2`, allowing its retry, prompt, and timeout policy to differ from chat.
- Retrieval embeddings default to `Snowflake/snowflake-arctic-embed-l-v2.0`, producing normalized 1024-dimensional vectors.
- `TextEmbedder` selects CUDA when available, otherwise CPU, and converts the model to fp16 on CUDA.
- Context-map budgeting uses the `cl100k_base` tokenizer configured in `harness.yaml`.

## Containers and Local Services

- `docker-compose.yml` defines PostgreSQL 18 with pgvector, a separate test PostgreSQL instance, and a single-node Vespa service.
- Named volumes are `deverino_pgdata`, `deverino_pgdata_test`, and `deverino_vespadata`.
- `Dockerfile` builds the default tool-execution image `deverino-python:latest` from `python:3.14-slim`.
- Container tools in `harness_poc/system_tools/container_*.py` prefer Podman and fall back to Docker.
- The tool container mounts the project workspace and a scratch area; limits and TTL are configured in `harness.yaml`.
- `Justfile` is the operational command surface for services, dashboard, tests, linting, type checks, workflows, and Vespa deployment.

## Quality Tooling

- Pytest 9 with pytest-asyncio drives unit, integration, pressure, retrieval, runtime, UI, and benchmark suites under `tests/`.
- Ruff targets Python 3.14 with broad lint, security, modernization, and typing-related rules.
- Astral `ty` provides static type checking.
- Integration tests are marked `integration`; real-model quality tests are marked `benchmark` and require explicit opt-in.
