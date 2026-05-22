# Phases 7-10: Compact Executable Spec

**Date:** 2026-05-22
**Parent:** [2026-05-22-testing-architecture-implementation-spec.md](./2026-05-22-testing-architecture-implementation-spec.md)
**Status:** Approved

---

## Phase 7: LLM Judge

**File:** `tests/bench/llm_judge.py`

Call a cheap model to score an answer 0.0-1.0 against a prompt.

```
llm_judge(prompt: str, answer: str, *, model_id: str, config: LLMConfig) -> float
```

- Format prompt with `{answer}` placeholder filled
- Build pydantic-ai `Agent` with `output_type=float` using `build_model(LLMConfig(provider=config.provider, model=model_id, base_url=config.base_url))`
- Return the parsed float
- Raise `ValueError` with raw response if parsing fails (strict, no retry)

Model construction: `build_model()` from `pydantic_runtime.py` accepts `LLMConfig` — construct a judge config with same `provider`/`base_url` but different `model`.

---

## Phase 8: Benchmark Fixtures

**File:** `tests/bench/conftest.py`

```
live_session fixture:
  scope: function
  returns: _LiveSession wrapper
  construction:
    - Read TEST_DATABASE_URL env var (default: harness.yaml's database_url)
    - build_app_state(database_url=TEST_DATABASE_URL)
    - Read BENCHMARK_MODEL env var (default: "claude-haiku-4-5-20251001")
    - state.goal_decision_model = build_model(LLMConfig matching BENCHMARK_MODEL)
    - Return _LiveSession(state)

rubric fixture:
  scope: function
  returns: Rubric
  convention: test_summarise_blackboard_database → summarise-blackboard-database.md

_LiveSession wrapper:
  state: AppState
  run(goal: str) -> GoalRunResult
    GoalRunner(max_iterations=30, max_tokens=20000).run(goal, state)

skip logic:
  pytest_addoption: --run-benchmarks (store_true, default=False)
  pytest_collection_modifyitems: if not --run-benchmarks, skip all tests/bench/
```

---

## Phase 9: First Benchmark Test

**File:** `tests/bench/test_goal_quality.py`

```python
@pytest.mark.benchmark
def test_summarise_blackboard_database(live_session, rubric):
    result = live_session.run(rubric.goal)
    rubric.assert_hard_gates(result)           # fail-fast
    score = rubric.judge(result.content)       # LLM judge
    assert score >= rubric.judge_threshold
```

---

## Phase 10: CI Config

**Justfile additions:**

```
test-unit:      pytest tests/unit/
test-agent:     pytest tests/agent/
test-integration: pytest tests/ -m integration
test-bench:     BENCHMARK_MODEL=claude-haiku-4-5-20251001 pytest tests/bench/ --run-benchmarks
```

**pyproject.toml markers:**

```toml
[tool.pytest.ini_options]
markers = [
    "integration: Requires Postgres and Vespa",
    "benchmark: Real-LLM quality benchmark (skipped by default, use --run-benchmarks)",
]
```
