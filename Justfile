# Deverino — common dev commands
# Run with: just <recipe>

# Auto-detect container compose backend (podman on Linux, docker on macOS)
compose := `command -v podman >/dev/null 2>&1 && echo "podman compose" || echo "docker compose"`

default:
    @just --list

# Start interactive REPL
repl:
    uv run harness-poc

# List all discovered skills
skills:
    uv run harness-poc skill list

# Show durable project state
state:
    uv run harness-poc state show project

# Show terminal dashboard snapshot
dashboard-summary:
    uv run harness-poc dashboard summary

# Start FastAPI dashboard server (API + static frontend): just dashboard 8050
dashboard port="8050":
    uv run harness-poc dashboard serve --port {{port}}

# Start API with auto-reload for development
dashboard-dev port="8050":
    uv run harness-poc dashboard serve --port {{port}} --debug

# Build dashboard frontend for production
dashboard-build:
    cd dashboard-ui && pnpm install && pnpm build

# Start frontend dev server with hot-reload (use with dashboard-dev for API)
dashboard-ui-dev:
    cd dashboard-ui && pnpm install && pnpm dev

# Start the local ACDL playground: just acdl-playground 8765
# Then open http://127.0.0.1:8765/acdl-preview.html
acdl-playground port="8765":
    python3 -m http.server {{port}} --directory docs/acdl

# Start backing services (Postgres + Vespa)
services-up:
    {{compose}} up -d postgres vespa

# Stop backing services without deleting data
services-down:
    {{compose}} stop

# Deploy Vespa application package
vespa-deploy:
    {{compose}} exec vespa vespa deploy /vespa-app

# Start just the main database
db-up:
    {{compose}} up -d postgres

# Stop the main database
db-down:
    {{compose}} stop postgres

# Run a workflow: just workflow <name> "<objective>"
workflow name objective:
    uv run harness-poc workflow run {{name}} "{{objective}}"

# Start the dedicated test database
test-db-up:
    {{compose}} up -d postgres_test

# Stop the dedicated test database
test-db-down:
    {{compose}} stop postgres_test

# Run full test suite
test: test-db-up
    TEST_DATABASE_URL=postgresql://deverino_test:deverino_test@localhost:5433/deverino_test uv run pytest

# Run unit tests only (no DB, no LLM)
test-unit:
    uv run pytest tests/unit/ tests/agent/

# Run agent tests only (mock LLM, in-memory DB)
# -v: verbose test names — see which test runs
# -s: no capture — see skill execution output in real time
# --tb=short: concise tracebacks on failure
test-agent:
    uv run pytest tests/agent/ -v -s --tb=short

# Run integration tests (needs Postgres + Vespa)
test-integration: test-db-up
    TEST_DATABASE_URL=postgresql://deverino_test:deverino_test@localhost:5433/deverino_test uv run pytest tests/ -m integration

# Run benchmarks (needs real LLM + Postgres)
test-bench model="claude-haiku-4-5-20251001": test-db-up
    BENCHMARK_MODEL={{model}} TEST_DATABASE_URL=postgresql://deverino_test:deverino_test@localhost:5433/deverino_test uv run pytest tests/bench/ --run-benchmarks

# Run a single test file: just test-file tests/test_goal_runner.py
test-file file: test-db-up
    TEST_DATABASE_URL=postgresql://deverino_test:deverino_test@localhost:5433/deverino_test uv run pytest {{file}}

# Lint with ruff
lint:
    uv run ruff check .

# Auto-fix lint issues
lint-fix:
    uv run ruff check . --fix

# Static type checks
types:
    uv run ty check

# Run lint + types + tests
check: lint types test
