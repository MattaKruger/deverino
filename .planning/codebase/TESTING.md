---
title: Testing Guide
mapped_at: 2026-07-11
last_mapped_commit: cf99f7e
focus: quality
---

# Testing

## Framework and Configuration

- Python tests use pytest 9 with `pytest-asyncio`; `asyncio_mode = "auto"` is configured in `pyproject.toml`.
- Registered markers are `integration` (PostgreSQL/Vespa) and `benchmark` (real LLM, opt-in).
- The current checkout contains 121 `test_*.py` modules across `tests/` and `harness_poc/v2/tests/`, with more
  than 1,100 syntactic test functions before parameter expansion.
- Assertions are plain pytest `assert`; Ruff intentionally relaxes assertion, annotation, private-access, magic
  value, and test-double rules under test paths.
- No coverage plugin, threshold, or coverage-report command is configured.

## Test Organization

- `tests/unit/`: pure functions, parsers, local event behavior, and SQLite-backed database operations. These must
  not construct `AppState`, call a real LLM, or require PostgreSQL.
- `tests/agent/`: full `GoalRunner` behavior with deterministic model responses and in-memory SQLite through
  `tests/agent/harness.py::SessionHarness`.
- `tests/bench/`: opt-in real-model quality checks driven by Markdown rubrics and hard gates before an LLM judge.
- `tests/event/`: v1 event types, store, bus, observer, and v1/v2 event fusion.
- `tests/context_map/`: distiller contracts, cartographer invariants, rendering, configuration, corpus isolation,
  and PostgreSQL/pgvector integration.
- `tests/runtime/`, `tests/skills/`, `tests/repl/`, `tests/cli/`, and `tests/infra/`: behavior grouped by delivery or
  runtime subsystem.
- `tests/retrieval/`: document processing and Vespa behavior; its local `conftest.py` currently skips the entire
  directory unless `--run-vespa` is supplied.
- `tests/pressure/`: lifecycle, ordering, isolation, schema, parsing, and failure-path pressure checks. Several
  tests are expected failures documenting known gaps.
- `harness_poc/v2/tests/`: tests co-located with the experimental v2 implementation rather than under top-level
  `tests/`; include them explicitly in focused verification.
- A few legacy/root tests remain directly under `tests/`; new tests should follow the existing domain directory
  closest to the production behavior.

## Shared Fixtures and Test Doubles

- `tests/conftest.py::db_engine` connects to the dedicated PostgreSQL test database and truncates every SQLModel
  table before each test. The session-scoped engine creates tables once.
- `tests/conftest.py::in_memory_engine` uses SQLite plus `StaticPool`, suitable for unit and agent tests.
- `tests/conftest.py::test_config` builds real repository paths with a test database and disables Logfire.
- `tests/conftest.py::session_runner` provides `(SkillRunner, session_id, BlackboardDatabase)` for skill tests.
- `tests/helpers.py` contains shared model-response factories, `RecordingEventBus`, and `TraceAssertions`; reuse
  these instead of recreating mock event infrastructure.
- `tests/agent/harness.py::SessionHarness` is the preferred closed-loop test surface. It mounts a real
  `SkillRunner`, deterministic model responses, SQLite, and optional per-skill result overrides.
- Prefer `pytest.MonkeyPatch` for environment, module attribute, and dependency substitution. Use small typed
  spies/fakes for domain interfaces; use `MagicMock` where only call interaction matters.
- Built-in fixtures such as `tmp_path` should isolate filesystem behavior. Tests must not rely on execution order
  or mutate developer runtime state.

## Integration and Opt-In Requirements

- PostgreSQL tests expect `postgresql://deverino_test:deverino_test@localhost:5433/deverino_test` unless
  `TEST_DATABASE_URL` overrides it. Start the service with `just test-db-up`.
- pgvector context-map tests need the PostgreSQL vector extension provided by the test container.
- Vespa tests require a running Vespa service and `--run-vespa`; the retrieval conftest applies the skip based on
  directory path, not solely on the `integration` marker.
- Benchmark tests require PostgreSQL, provider credentials, and a live model. They run only with
  `--run-benchmarks`; `BENCHMARK_MODEL` and `BENCHMARK_JUDGE_MODEL` select models.
- External network/model calls are forbidden in normal deterministic tests. Mount a fake, model response factory,
  or `skill_overrides` entry instead.
- Container and CLI integration tests may require Docker/Podman and real workflow files; mark such tests
  `integration` and keep their side effects isolated.

## Commands

```bash
uv run pytest tests/unit/ tests/agent/
just test-agent
just test
just test-integration
just test-bench
uv run pytest harness_poc/v2/tests/ tests/event/ tests/unit/ -q
uv run ruff check tests/ harness_poc/v2/tests/
uv run ty check
cd dashboard-ui && pnpm build
```

- `just test` starts the PostgreSQL test service and runs the full top-level suite with `TEST_DATABASE_URL` set.
- `just test-unit` currently runs both `tests/unit/` and `tests/agent/`; despite its comment, it is the fast
  deterministic suite rather than unit tests alone.
- Use `just test-file path/to/test_file.py` for a PostgreSQL-backed focused run.
- For a changed behavior, run its narrow test first, then the relevant layer, then lint/type checks.

## Test Patterns

- Name tests by observable behavior, e.g. `test_skips_malformed_event_payload_and_continues`.
- Use `pytest.mark.parametrize` for repeated input/output cases and `pytest.raises(..., match=...)` for validation
  and error contracts.
- Assert event ordering and durable outcomes, not internal call counts, when testing orchestration.
- Async bus/runtime behavior uses normal `async def` tests under pytest-asyncio; explicit `@pytest.mark.asyncio`
  appears where clarity or local compatibility is useful.
- Database tests assert both persisted values and isolation/order semantics. Clean up explicitly only when the
  shared truncation fixture cannot own the resource.
- CLI tests use `typer.testing.CliRunner`; API tests exercise FastAPI routes; TUI tests mount controlled fakes and
  monkeypatch submission handlers rather than launching interactive processes.
- Benchmarks pair `tests/bench/test_<name>.py` with `tests/bench/rubrics/<name>.md`; deterministic hard assertions
  run before the paid LLM judge.

## Coverage Gaps and Risks

- `dashboard-ui/` has no Vitest, Playwright, or other frontend test configuration. `pnpm build` is currently the
  only automated TypeScript/Vue check.
- There is no measured Python coverage or minimum threshold, so test volume does not prove branch coverage.
- Retrieval skip logic excludes every file under `tests/retrieval/` without `--run-vespa`, including tests that
  could otherwise use fakes; this reduces default feedback.
- Some PostgreSQL/pgvector tests use `db_engine` without an `integration` marker, so `pytest -m` selection does not
  fully describe external-service requirements.
- Numerous `xfail` pressure tests record known parser, ordering, session-isolation, and lifecycle gaps. Review
  these before extracting the associated runtime contracts.
- API response types and `dashboard-ui/src/types/dashboard.ts` are manually mirrored with no contract test.
- v2 tests are outside top-level `tests/`, so commands targeting only `tests/` can miss regressions in the parallel
  orchestration implementation.
- Random vectors appear in pgvector integration tests without an explicit seed, creating avoidable statistical
  nondeterminism even though thresholds are broad.
- `tests/GUIDE.md` describes three primary layers, but the expanded current directory taxonomy is not fully
  documented there; contributors must infer placement for context-map, pressure, retrieval, and v2 tests.
