# Handoff: Testing Architecture

**Date:** 2026-05-22
**Status:** Phases 1-10 delivered, unit layer filled. Agent coverage: narrow — needs multi-skill chain tests.

---

## What was built

Three-layer testing architecture for the Deverino agentic harness.

```
tests/
  helpers.py                    ← RecordingEventBus + TraceAssertions + Mock infra
  conftest.py                   ← in_memory_engine fixture (+ existing db_engine)

  unit/                         ← 88 tests, <0.2s, zero fixtures (pure) or in-memory DB
    test_events.py              ← Event validation, auto-population, EVENT_REGISTRY (14)
    test_llm_client.py          ← LLMResponse immutability, Message/ToolCall shapes (13)
    test_processor_helpers.py   ← _prompt_from_event, _parse_skill_request, etc. (21)
    test_circuit_breaker.py     ← run_circuit_breaker — failure counting, token budget (7)
    test_skill_runner_parsing.py ← parse_skill_document, aliases, arg normalization (18)
    test_database_core.py       ← start_session, write_memory, read_memory, list keys (14)

  agent/                        ← 5 tests, <2s, no DB needed
    harness.py                  ← SessionHarness: build([...]), run(), assert_*()
    conftest.py                 ← response factory re-exports
    test_goal_loop.py           ← ReAct loop integration tests

  bench/                        ← scaffolded, opt-in via --run-benchmarks
    rubric_loader.py            ← Rubric parser + hard gates
    llm_judge.py                ← pydantic-ai judge (real LLM)
    conftest.py                 ← live_session + rubric fixtures + skip logic
    test_goal_quality.py        ← first benchmark test
    rubrics/
      summarise-blackboard-database.md
```

## How to run

```bash
# Unit tests (pure functions + in-memory DB, no Postgres, no LLM)
just test-unit                          # 88 tests, ~3s

# Agent tests (mock LLM, in-memory DB)
just test-agent                         # 5 tests, <2s

# All fast tests
uv run pytest tests/unit/ tests/agent/  # 93 tests, ~3s

# Integration tests (needs Postgres + Vespa)
just test-integration

# Benchmarks (needs Postgres + API keys)
just test-bench                          # haiku default
just test-bench claude-sonnet-4-6        # cross-model
```

## How to write a unit test

1. Create `tests/unit/test_<thing>.py`
2. Add file-level noqa: `# ruff: noqa: ANN201, FBT003`
3. Use `in_memory_engine` fixture for DB-dependent tests
4. Use `EventBus(EventStore(in_memory_engine))` for async event processor tests
5. Pure function tests need no fixtures at all

**Layer rules:**

| Constraint | Unit | Agent | Bench |
|-----------|------|-------|-------|
| Imports `AppState` or `build_app_state` | ✗ | ✓ | ✓ |
| Uses `SessionHarness` | ✗ | ✓ | ✗ |
| Real LLM calls | ✗ | ✗ | ✓ |
| Postgres | ✗ | ✗ | ✓ |
| Mock LLM (FunctionModel) | ✗ | ✓ | ✗ |
| In-memory SQLite | ✓ | ✓ | ✗ |

## How to write a new agent test

1. Create `tests/agent/test_<thing>.py`
2. Add file-level noqa: `# ruff: noqa: ANN201, FBT003`
3. Import: `from tests.agent.harness import SessionHarness` + factories from `tests.helpers`
4. Build scenario with `SessionHarness.build([...])` — each element is one LLM iteration
5. Run: `harness.run("goal string")`
6. Assert with `harness.assert_skill_called()`, `harness.assert_completed()`, etc.

Three mock response factories:
- `tool_call_response("name", {"arg": "val"})` — model calls a skill
- `evaluate_goal_response(True, "reasoning", "final answer")` — model says done
- `text_response("thinking...")` — model output with no tool call

**Gotcha:** `evaluate_goal` is intercepted by GoalRunner — it emits `GoalEvaluated`, not `SkillCalled`. Don't include it in `assert_skill_order()` or rubric `skill_sequence`.

## How to write a rubric

Create `tests/bench/rubrics/<slug>.md`:

```markdown
# Rubric: <slug>

## Goal
<goal string>

## Hard Assertions
- must_contain: "expected phrase"
- must_not_contain: "I don't know"
- min_words: 20
- skill_sequence: [read_memory]   # non-intercepted skills only

## LLM Judge
threshold: 0.7
model: claude-haiku-4-5-20251001
prompt: |
  Score 0.0-1.0: does the answer correctly ...
  Answer: {answer}
```

Load and validate:
```python
rubric = Rubric.from_markdown(Path("tests/bench/rubrics/<slug>.md"))
rubric.assert_hard_gates(result)                        # deterministic gates
rubric.judge(result.content, config=llm_config)         # LLM score
```

## Key design decisions

| Decision | Choice | Why |
|----------|--------|-----|
| Mock infrastructure location | `tests/helpers.py` | Single source of truth; both `harness.py` and old `test_goal_runner.py` import from here |
| Agent test DB | In-memory SQLite via `StaticPool` | No Postgres drift; shared construction path via `database_url` param |
| SessionHarness construction | Manual wiring (not `build_app_state`) | Need `RecordingEventBus` instead of `EventBus` |
| Unit test DB | In-memory SQLite via `in_memory_engine` fixture | No Postgres; async processor tests use `EventBus(EventStore(in_memory_engine))` |
| Rubric format | Markdown sections | Readable as documentation; parseable as structured data |
| Rubric hard gates | Fail-fast | Deterministic, free; first failure enough to diagnose |
| LLM judge model | Configurable per rubric, default cheap (haiku) | Keep benchmark costs predictable |
| Benchmark skip | `--run-benchmarks` opt-in | Prevents accidental token spend |
| Unit test layer rule | No `AppState` or `build_app_state` imports | Keeps unit/agent boundary hard |

## What was discovered during unit testing

- `BlackboardDatabase._utc_now()` truncates to seconds — `get_last_session_id` ordering is non-deterministic within the same second. Tests that depend on temporal ordering need explicit `time.sleep(1.1)`.
- `SkillRunner.parse_skill_document` silently provides a default empty schema when `parameters` is missing from frontmatter — it does not raise.

## Current coverage gaps

| Area | Covered by | Gap |
|------|-----------|-----|
| Event models | `test_events.py` (14 tests) | None |
| LLM client types | `test_llm_client.py` (13 tests) | None |
| Processor helpers | `test_processor_helpers.py` (21 tests) | `_parse_skill_request` could test escaped JSON edge cases |
| Circuit breaker | `test_circuit_breaker.py` (7 tests) | Combined failure + budget scenario; race conditions |
| Skill parsing | `test_skill_runner_parsing.py` (18 tests) | YAML edge cases (malformed YAML, duplicate keys) |
| Database core | `test_database_core.py` (14 tests) | `append_session_messages`, `load_session_messages`, state proposals |
| ReAct loop (agent) | `test_goal_loop.py` (5 tests) | **Multi-skill chains, stuck detection, context window trimming** |
| Benchmarks | 1 rubric, 1 test | More rubrics for different goal types |

## Next phase: multi-skill chain agent tests

The 5 agent tests cover atomic ReAct patterns. Missing: tests that demonstrate how skills chain together in a session — this is where the system's behavior actually emerges. Priority tests:

- `read_memory` → `evaluate_goal` (two-skill chain with data dependency)
- `search_documents` → `read_memory` → `evaluate_goal` (three-skill chain)
- Stuck detection: model repeats the same `read_memory` call 3+ times
- Context window: model sees truncated skill output from earlier turns
- `search_documents` → error → `evaluate_goal` (error recovery chain)

All use existing `SessionHarness` — no new infra required.

## Files changed outside tests/

- `harness_poc/app_factory.py` — `build_identity()` and `build_app_state()` accept optional `database_url` param
- `pyproject.toml` — added `integration` and `benchmark` pytest markers
- `Justfile` — added `test-unit`, `test-agent`, `test-integration`, `test-bench` targets

## Spec documents

- `docs/superpowers/specs/2026-05-22-testing-architecture-design.md` — original design
- `docs/superpowers/specs/2026-05-22-testing-architecture-implementation-spec.md` — detailed spec
- `docs/superpowers/specs/2026-05-22-testing-architecture-phases-7-10.md` — compact phases 7-10
