# Test Migration Plan — Part 2

## Convention summary (from `tests/unit/` and `tests/agent/`)

1. **Domain directories** group by architectural layer, not test type.
2. **Shared fixtures** live in `tests/conftest.py` — no inline fixture duplication.
3. **Shared mock infrastructure** lives in `tests/helpers.py` — `RecordingEventBus`, `SessionHarness`, `tool_call_response()`, etc.
4. **Internal imports** use the package path: `from tests.helpers import ...`, `from tests.agent.harness import ...`.
5. **`db_engine`** for persistence-dependent tests; **`in_memory_engine`** for pure unit tests.
6. **`@pytest.mark.integration`** for tests needing Postgres/Vespa/Docker.
7. **`tests/bench/`** and **`tests/agent/`** are already organized and left untouched.

---

## Phase 1 — Delete dead weight (4 items, ~5 minutes)

| # | File | Action |
|---|---|---|
| 1 | `tests/test_document_models.py` | **Delete entire file.** Two tests verify `SQLModel.metadata.create_all()` worked — not harness behavior. |
| 2 | `tests/test_event_bus.py` lines 13–49 | **Delete 4 tests** (`test_recording_bus_*`). Testing `RecordingEventBus` — which is test infrastructure from `helpers.py`. |
| 3 | `tests/test_session_restore.py` lines 46–61 | **Delete `test_get_last_session_id` and `test_session_exists`.** Covered by `tests/unit/test_database_core.py::test_get_last_session_id` and `test_session_exists_after_start`. |
| 4 | `tests/test_events.py` line 35 | **Remove duplicate `"SkillCancelled"`** entry in `test_event_registry_covers_all_concrete_types`. |

---

## Phase 2 — Extract shared fixtures to `conftest.py` (~30 minutes)

14 files define a nearly identical `_test_config` helper; 8 of those also define `_runner`. This is
the most duplicated code in the test suite.

**Add to `tests/conftest.py`:**

```python
@pytest.fixture
def test_config(db_engine: Engine) -> HarnessConfig:
    """HarnessConfig wired to real project paths and the test database."""
    repo_root = Path.cwd()
    return HarnessConfig(
        project_root=repo_root,
        config_path=repo_root / "harness.yaml",
        paths=HarnessPaths(
            soul=repo_root / "harness_poc/system_prompts/SOUL.md",
            system_tools=repo_root / "harness_poc/system_tools",
            system_skills=repo_root / "harness_poc/system_skills",
            project_skills=repo_root / "skills",
            workflows=repo_root / "workflows",
            pipelines=repo_root / "pipelines",
            personas=repo_root / "personas",
        ),
        llm=LLMConfig(provider="mock"),
        runtime=RuntimeConfig(
            database_url=db_engine.url.render_as_string(hide_password=False),
        ),
        observability=ObservabilityConfig(enabled=False),
    )

@pytest.fixture
def session_runner(
    test_config: HarnessConfig, db_engine: Engine
) -> tuple[SkillRunner, str, BlackboardDatabase]:
    """Bootstrap a session + SkillRunner. Returns (runner, session_id, database)."""
    database = BlackboardDatabase(db_engine)
    session_id = database.start_session("test")
    runner = SkillRunner(database=database, config=test_config)
    return runner, session_id, database
```

**Files to update (all 14 with `_test_config`):**

| File | Has `_runner`? | Action |
|---|---|---|
| `tests/test_read_memory.py` | Yes | Replace both with `test_config` + `session_runner` |
| `tests/test_summarize_memory.py` | Yes | Same |
| `tests/test_evaluate_goal.py` | Yes | Same |
| `tests/test_delegate_task.py` | Yes | Same + fix return order (see below) |
| `tests/test_review_work.py` | Yes | Same |
| `tests/test_reflect_on_result.py` | Yes | Same |
| `tests/test_semble_search.py` | Yes | Same |
| `tests/test_spec_writer.py` | Yes | **Exception** — needs `project_root=tmp_path`. Keep inline or add `test_config_tmp` fixture. |
| `tests/test_consolidate_state.py` | No | Replace `_test_config` with `test_config` |
| `tests/test_repl_skill_execution.py` | No | Replace `_test_config` with `test_config` |
| `tests/test_container_skills.py` | No | **Keep inline.** Takes `default_container_image` param not covered by shared fixture. |
| `tests/test_execute_python.py` | No | Replace `_test_config` with `test_config` |
| `tests/test_pydantic_runtime.py` | No | Replace `_test_config` with `test_config` |
| `tests/test_skill_cancellation.py` | No | Replace `_test_config` with `test_config` |

**Fix while here:** `test_delegate_task.py:97` returns `tuple[SkillRunner, BlackboardDatabase, str]` — database before session_id. Normalize to `(runner, session_id, database)` like every other file. All call sites in that file destructure as `runner, database, session_id = _runner(db_engine)` and need updating to match.

---

## Phase 3 — Deduplicate goal loop tests + relocate outliers (~15 minutes)

`tests/test_goal_runner.py` and `tests/agent/test_goal_loop.py` test the same scenarios. The
agent-layer versions are cleaner (use `SessionHarness`). **Keep the agent versions.**

**Remove from `tests/test_goal_runner.py` (5 duplicates):**

| Duplicate test | Already covered by |
|---|---|
| `test_completes_on_evaluate_goal_true` | `agent/test_goal_loop.py::test_completes_on_direct_evaluate_goal` |
| `test_text_response_without_tool_call` | `agent/test_goal_loop.py::test_text_response_without_tool_call` |
| `test_iteration_budget_exhausted` | `agent/test_goal_loop.py::test_iteration_budget_exhausted` |
| `test_skill_execution_error_handled` | `agent/test_goal_loop.py::test_skill_error_does_not_crash_loop` |
| `test_evaluate_goal_stub_execute` | `test_evaluate_goal.py::test_evaluate_goal_echoes_inputs_when_complete` |

**Keep in `tests/test_goal_runner.py` (migrated to `tests/runtime/test_goal_runner.py` in Phase 4):**

| Test | Reason to keep |
|---|---|
| `test_completed_generation_goal_prefers_final_answer` | Tests final_answer extraction logic |
| `test_completed_generation_goal_uses_latest_artifact_for_meta_reasoning` | Tests artifact fallback |
| `test_continues_on_evaluate_goal_false` | Agent harness has no multi-iteration test yet |
| `test_token_budget_exhausted` | Token budget ≠ iteration budget |
| `test_goal_token_budget_uses_context_delta` | Tests context-aware token counting |
| `test_stuck_detection_blocks_repeated_failed_action` | Tests semantic stuck detection + `_semantic_key` |
| `test_context_window_builds_from_events` | Tests context window construction |
| `test_goal_runner_streams_progress` | Tests streaming callback |
| `test_evaluate_goal_skill_registered` | Move to `tests/skills/` (Phase 4) |
| `test_review_work_skill_executes` | Move to `tests/skills/` (Phase 4) |

**Relocate from `tests/test_goal_runner.py` (4 outliers not goal-loop tests):**

| Test | Destination | Reason |
|---|---|---|
| `test_count_tokens_basic` | `tests/unit/test_token_counting.py` (new) | Unit test for `count_tokens()` |
| `test_count_tokens_scales_with_length` | `tests/unit/test_token_counting.py` (new) | Same |
| `test_goal_cli_command_help` | `tests/infra/test_cli.py` (merge into existing) | CLI integration test |
| `test_goal_cli_executes_with_mock` | `tests/infra/test_cli.py` (merge into existing) | Same |

---

## Phase 4 — Domain directory migration (~35 minutes)

### Target layout

```
tests/
├── conftest.py              # db_engine, in_memory_engine, test_config, session_runner
├── helpers.py               # RecordingEventBus, mock LLM helpers, TraceAssertions
│
├── unit/                    # ✓ already done
│   ├── test_database_core.py
│   ├── test_llm_client.py
│   ├── test_skill_runner_parsing.py
│   ├── test_circuit_breaker.py
│   └── test_token_counting.py        # NEW — moved from test_goal_runner.py
│
├── agent/                   # ✓ already done (left untouched)
│   ├── harness.py
│   ├── test_goal_loop.py
│   └── test_skill_chains.py
│
├── bench/                   # ✓ already done (left untouched)
│   ├── llm_judge.py
│   ├── rubric_loader.py
│   ├── test_goal_quality.py
│   └── rubrics/
│
├── event/                   # NEW — event system layer
│   ├── test_events.py
│   ├── test_event_store.py
│   ├── test_event_bus.py
│   └── test_event_log_observer.py
│
├── skills/                  # NEW — skill execution through SkillRunner
│   ├── test_read_memory.py
│   ├── test_summarize_memory.py
│   ├── test_evaluate_goal.py
│   ├── test_delegate_task.py
│   ├── test_review_work.py
│   ├── test_reflect_on_result.py
│   ├── test_consolidate_state.py
│   ├── test_spec_writer.py
│   ├── test_knowledge_tools.py
│   ├── test_context_map.py
│   ├── test_web_search.py
│   └── test_semble_search.py
│
├── retrieval/               # NEW — document indexing, Vespa, chunking
│   ├── test_document_db.py
│   ├── test_document_index.py
│   ├── test_vespa_client.py
│   ├── test_vespa_integration.py      # @pytest.mark.integration
│   ├── test_search_documents.py
│   ├── test_index_documents.py
│   ├── test_auto_index_bootstrap.py
│   ├── test_pdf_converter.py
│   └── test_retrieval_chunking.py     # text chunking utilities
│
├── repl/                    # NEW — interactive REPL + TUI layer
│   ├── test_repl_chat.py
│   ├── test_repl_skill_execution.py
│   ├── test_skill_cancellation.py
│   ├── test_repl_completion.py
│   ├── test_repl_direct_invocation.py
│   ├── test_tui.py
│   ├── test_tui_throttle.py
│   └── test_tui_vim.py
│
├── runtime/                 # NEW — goal runner, pipelines, materializer, streaming
│   ├── test_goal_runner.py           # (remaining after Phase 3 cleanup)
│   ├── test_execute_python.py
│   ├── test_container_skills.py
│   ├── test_pydantic_runtime.py
│   ├── test_message_history.py
│   ├── test_tool_worker.py
│   ├── test_tool_event_callback.py
│   ├── test_pipeline_runner.py
│   ├── test_materializer_runner.py
│   └── test_streaming_context.py
│
└── infra/                   # NEW — config, permissions, CLI, dashboard, session restore
    ├── test_config.py
    ├── test_blackboard_proxy.py
    ├── test_session_restore.py       # (remaining test after Phase 1 cleanup)
    ├── test_dashboard.py
    ├── test_cli.py                   # absorbs test_goal_cli_* from test_goal_runner.py
    ├── test_permissions.py
    ├── test_console_adapter.py
    └── test_docker_compose.py
```

**Notes on what stays and what moves:**

- `tests/agent/` — already organized; `test_skill_chains.py` stays put.
- `tests/bench/` — quality benchmark framework; left untouched.
- `tests/cli/` — empty directory (only `__init__.py`). **Delete the directory.** CLI tests live in `tests/infra/test_cli.py`.
- `tests/skills/` — currently empty `__init__.py` only. Remove it; files land directly in the new `tests/skills/` directory (namespace packages).
- `test_goal_runner.py` skill-catalog tests (`test_evaluate_goal_skill_registered`, `test_review_work_skill_executes`) move to `tests/skills/` during this phase.

**Migration rules:**
- Move the file, update `from tests.helpers import ...` — no change needed (package path stays the same).
- Run `ruff check .` to catch any missed imports.
- No `__init__.py` needed in domain directories (namespace packages work).

---

## Phase 5 — Convert `smoke_test_skills.py` to pytest (~15 minutes)

Currently a standalone script with its own `main()`. Convert to a parametrized test in `tests/skills/`:

```python
# tests/skills/test_smoke.py

import pytest

SMOKE_CASES = [
    ("evaluate_goal", {"is_complete": True, "reasoning": "smoke test"}, {"success"}),
    ("read_memory", {}, {"success"}),
    ("read_memory", {"memory_key": "nonexistent"}, {"failed"}),
    ("review_work", {"objective": "test", "memory_key": "test_key"}, {"success"}),
    ...
]

@pytest.mark.parametrize("skill_name,arguments,expected", SMOKE_CASES)
def test_skill_smoke(
    session_runner: tuple,
    skill_name: str,
    arguments: dict,
    expected: set[str],
) -> None:
    runner, session_id, _ = session_runner
    result = runner.execute_skill(
        tool_name=skill_name, arguments=arguments, session_id=session_id
    )
    assert result.status in expected, (
        f"{skill_name}: expected status in {expected}, got {result.status}"
    )
```

Delete `tests/smoke_test_skills.py`.

---

## Phase 6 — Tag integration tests (~5 minutes)

Add `@pytest.mark.integration` to tests that need external services beyond Postgres:

| File (post-migration) | Reason |
|---|---|
| `tests/retrieval/test_vespa_integration.py` | Needs Vespa |
| `tests/retrieval/test_vespa_client.py` | Needs Vespa |
| `tests/retrieval/test_search_documents.py` | Needs Vespa |
| `tests/retrieval/test_index_documents.py` | Needs Vespa |
| `tests/infra/test_cli.py::test_workflow_run_executes_workflow_without_container_block` | Reads a live workflow YAML |

---

## Post-migration verification

After all phases complete, run:

```bash
uv run pytest                          # full suite
uv run ruff check tests/               # lint + import verification
```

Expected: zero root-level test files remain in `tests/` beyond `conftest.py`, `helpers.py`, and `__init__.py`.

---

## Summary — things that go away

| What | Why |
|---|---|
| `tests/test_document_models.py` | Tests SQLModel internals |
| 4 `RecordingEventBus` tests | Tests test infrastructure |
| 2 session lifecycle tests in `test_session_restore.py` | Duplicate of unit tests |
| 5 goal loop tests in `test_goal_runner.py` | Duplicate of agent-layer tests |
| 1 evaluate_goal test in `test_goal_runner.py` | Duplicate of `test_evaluate_goal.py` |
| 2 token-counting tests in `test_goal_runner.py` | Moved to `tests/unit/` |
| 2 CLI tests in `test_goal_runner.py` | Moved to `tests/infra/test_cli.py` |
| 2 skill-catalog tests in `test_goal_runner.py` | Moved to `tests/skills/` |
| `tests/smoke_test_skills.py` | Converted to pytest parametrized |
| 14 copies of `_test_config()` | Replaced by 1 fixture (1 file keeps inline variant) |
| 8 copies of `_runner()` | Replaced by 1 fixture (1 file keeps inline variant) |
| Duplicate `"SkillCancelled"` in `test_events.py` | Bug fix |
| `tests/cli/` empty directory | CLI tests live in `tests/infra/` |
| `tests/skills/__init__.py` | Namespace packages don't need it |
| 43 root-level test files | Moved to 7 domain directories |

## Estimated total time: ~105 minutes
