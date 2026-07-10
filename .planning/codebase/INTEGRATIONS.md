---
title: External Integrations
mapped_at: 2026-07-11
last_mapped_commit: cf99f7e
focus: tech
---

# External Integrations

## Model Providers

- `harness_poc/core/runtime/pydantic_runtime.py` is the model-provider boundary used by the main runtime, delegation, compilation, and other model-backed operations.
- Anthropic uses PydanticAI `AnthropicModel` with `AnthropicProvider` and `ANTHROPIC_API_KEY`.
- DeepSeek uses PydanticAI `OpenAIChatModel` with `DeepSeekProvider` and `DEEPSEEK_API_KEY`.
- OpenAI uses `OpenAIChatModel` with `OpenAIProvider`, `OPENAI_API_KEY`, and an optional custom `base_url`.
- GLM shares the OpenAI-compatible path, uses `GLM_API_KEY`, and currently targets `https://open.bigmodel.cn/api/coding/paas/v4`.
- API settings search for a `.env` from the current directory upward; normal process environment variables remain supported.
- `HARNESS_FAKE_LLM` forces PydanticAI `TestModel`; absent provider credentials also produce the offline fallback rather than a startup failure.
- The provider boundary is not fully generic: supported provider names are selected by explicit branches in `build_model()`.

## PostgreSQL and pgvector

- `harness_poc/core/storage/db_engine.py` creates SQLAlchemy engines with `pool_pre_ping=True` and registers the pgvector psycopg2 adapter for PostgreSQL.
- `harness_poc/core/storage/database.py` is the application persistence facade and creates or incrementally ensures its schema at startup.
- The database stores session history, event streams, state projections/proposals, context-map source events and materializations, document indexing metadata, and token/observability data.
- `docker-compose.yml` exposes the runtime database on `localhost:5432` and the test database on `localhost:5433`.
- The database URL is a host configuration boundary in `harness.yaml`; most runtime components receive `BlackboardDatabase` or a restricted `BlackboardAccessProxy` rather than opening connections directly.
- SQLite remains an adapter-compatible test path, but pgvector features and PostgreSQL JSONB behavior are PostgreSQL-specific.

## Vespa Retrieval

- `harness_poc/core/retrieval/vespa_client.py` is the thin PyVespa adapter for health checks, document feeds, queries, and deletes.
- `harness_poc/core/retrieval/retrieval.py` defines the `VespaDocumentClient` protocol consumed by indexing and search code.
- The configured endpoint is `http://localhost:8080`, namespace `deverino`, schema `doc_chunk`, with a five-second query timeout.
- `vespa/document_retrieval/` is the deployable Vespa application package; the config server is exposed on port 19071.
- `harness_poc/app_factory.py` optionally health-checks and auto-indexes configured project paths on interactive startup.
- `HARNESS_SKIP_AUTO_INDEX` disables that startup integration for tests and commands where indexing is unwanted.
- `skills/index_documents/` and `skills/search_documents/` expose retrieval to agents; PostgreSQL records source status while Vespa holds the searchable documents.

## Embedding Model Registry

- `harness_poc/core/retrieval/embedder.py` loads `Snowflake/snowflake-arctic-embed-l-v2.0` through Sentence Transformers.
- The first use may download model artifacts from the Hugging Face ecosystem; the model is cached in-process by model/device pair.
- Query and passage embeddings use task-specific prompts, and the 1024-dimensional output must match the Vespa schema.
- CUDA is optional. CPU is the fallback, so the integration boundary is performance-sensitive but not GPU-mandatory.
- `harness_poc/core/context_map/copt_gate.py` separately uses Sentence Transformers for context-map similarity gating.

## Document Conversion and OCR

- `harness_poc/core/retrieval/pdf_converter.py` uses Docling and PyMuPDF for local document/PDF conversion.
- `retrieval.ocr_service_url` can redirect PDF conversion to an HTTP service exposing `POST /convert`; it is unset in the checked-in `harness.yaml`.
- `scripts/ocr_service.py` provides the companion service implementation for that optional boundary.
- Remote conversion uses a JSON payload containing file path, URI, title, kind, and token limit, with a 300-second request timeout.

## Web and Research Services

- `skills/web_search/skill.py` integrates with LangSearch at `https://api.langsearch.com/v1/web-search` using `LANGSEARCH_API_KEY`.
- Without a LangSearch key, the skill reports configuration guidance and can expose mock behavior rather than silently making another provider call.
- `scripts/search_arxiv.py` uses the public arXiv Atom API and arXiv PDF URLs through stdlib `urllib`; it is a project script, not a core runtime dependency.
- `skills/semble_search/skill.py` executes the local `semble` CLI as a subprocess for semantic code search rather than calling a hosted API directly.

## Observability

- `harness_poc/core/observability/logfire_subscriber.py` configures Logfire and instruments PydanticAI.
- When `observability.logfire` is enabled, `harness_poc/app_factory.py` subscribes Logfire handlers to the in-process `EventBus`.
- `LOGFIRE_TOKEN` supplies remote credentials; `logfire_include_content` controls whether prompt/tool content is exported.
- Local rotating file logging remains independent and is configured through `HARNESS_LOG_LEVEL`, `HARNESS_LOG_FILE`, `HARNESS_LOG_MAX_MB`, `HARNESS_LOG_BACKUPS`, and `HARNESS_LOG_STDERR`.

## Dashboard API Boundary

- `harness_poc/api/__init__.py` creates a FastAPI app over the same database URL used by the harness.
- `harness_poc/api/routes.py` exposes read-oriented dashboard endpoints plus compilation operations; `harness_poc/api/chat.py` exposes session and streaming chat operations.
- Streaming uses Server-Sent Events, consumed by `dashboard-ui/src/api/sse.ts`; dashboard stores also poll ordinary JSON endpoints.
- During development, Vite proxies `/api` to Uvicorn on port 8050. Production static serving is intentionally left to nginx or another static server.
- CORS currently allows all origins, methods, and headers with credentials; there is no authentication layer at this API boundary.

## Container Runtime Boundary

- `harness_poc/system_tools/container_spawn.py`, `container_exec.py`, and `container_destroy.py` call Podman or Docker CLIs through `subprocess`.
- Backend resolution prefers `podman`, then `docker`; the `Justfile` separately chooses `podman compose` when available.
- The default execution image is configured as `deverino-python:latest` and can be built automatically from the repository `Dockerfile`.
- Container lifecycle state is recorded in blackboard shared memory, while the actual runtime remains an external process boundary.
- Container controls include image choice, TTL, maximum harness-owned containers, workspace/scratch mounts, and command timeouts.

## Integration Boundary Summary

- Typed producer/consumer coordination remains inside the process through `EventBus`; PostgreSQL supplies durability rather than cross-process event transport.
- SQLModel/SQLAlchemy isolate most database access, PyVespa isolates the search service, and PydanticAI isolates most model SDK differences.
- Skills and system tools are the extension boundary for project-specific HTTP, subprocess, database, and search integrations.
- `harness.yaml` owns non-secret endpoints and policies; `.env` or process environment variables own provider and service credentials.
