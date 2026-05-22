# Handoff: Testing Architecture

**Date:** 2026-05-22
**Status:** Phases 1-10 delivered, ready for use

---

## What was built

Three-layer testing architecture for the Deverino agentic harness.

```
tests/
  helpers.py                    ← RecordingEventBus + TraceAssertions + Mock infra
  conftest.py                   ← in_memory_engine fixture (+ existing db_engine)

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

  unit/                         ← directory exists, fill on-contact
```

## How to run

```bash
# Agent tests (fast, no DB)
just test-agent

# Integration tests (needs Postgres + Vespa)
just test-integration

# Benchmarks (needs Postgres + API keys)
just test-bench                          # haiku default
just test-bench claude-sonnet-4-6        # cross-model
```

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
| Rubric format | Markdown sections | Readable as documentation; parseable as structured data |
| Rubric hard gates | Fail-fast | Deterministic, free; first failure enough to diagnose |
| LLM judge model | Configurable per rubric, default cheap (haiku) | Keep benchmark costs predictable |
| Benchmark skip | `--run-benchmarks` opt-in | Prevents accidental token spend |

## Files changed outside tests/

- `harness_poc/app_factory.py` — `build_identity()` and `build_app_state()` accept optional `database_url` param
- `pyproject.toml` — added `integration` and `benchmark` pytest markers
- `Justfile` — added `test-unit`, `test-agent`, `test-integration`, `test-bench` targets

## Spec documents

- `docs/superpowers/specs/2026-05-22-testing-architecture-design.md` — original design
- `docs/superpowers/specs/2026-05-22-testing-architecture-implementation-spec.md` — detailed spec
- `docs/superpowers/specs/2026-05-22-testing-architecture-phases-7-10.md` — compact phases 7-10
