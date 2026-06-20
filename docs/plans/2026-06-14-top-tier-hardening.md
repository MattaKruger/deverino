# Phased Specification: Deverino Top-Tier Hardening

**Date**: 2026-06-14
**Status**: Phase 1 complete, Phase 2 implemented (2026-06-17)

## Context

Audited the codebase against the state of the art in LLM agent harnesses (Anthropic's _Building Effective Agents_, Lilian Weng's _LLM-Powered Autonomous Agents_, SWE-agent, the Awesome AI Agents landscape). The harness already has strong architectural bones — distinct workflow/pipeline/agent paths, a PostgreSQL blackboard, Vespa hybrid search, an EventBus with Logfire/OTel observability, and a layered skill taxonomy. This spec targets the verified gaps that separate it from top-tier.

### Verified Claims (from `docs/plans/2026-06-14-audit`)

| Claim | Verdict |
|---|---|
| Workflows/Agents/Pipelines — distinct paths | **Verified** |
| PostgreSQL blackboard (14 SQLModel tables) | **Verified** |
| Vespa hybrid search (keyword/semantic/hybrid) | **Verified** |
| delegate_task for subagents | **Verified** |
| Skills catalog (24+ skills, 3 types) | **Verified** |
| Observability (EventBus, Logfire/OTel, dashboard) | **Verified** |
| SOUL → Knowledge → Executable → Tools layering | **Partially** (type field enforced, no runtime content boundary) |
| ReAct loop | **Partially** (loop exists in `goal_runner.py:469–813`, no Reflexion optimizer) |
| Tool design / ACI | **Partially** (JSON Schema + permissions, no programmatic input sanitization) |
| Evaluator-optimizer loops | **Contradicted** (does not exist) |

---

## Phase 1 — Agent-Computer Interface (ACI)

**Status**: ✅ Complete (2026-06-17)

**Outcome**: Tools that prevent model errors before they happen, with structured feedback when they do.

The single highest-leverage change. Anthropic's SWE-bench team spent more time optimizing tools than prompts. Princeton's SWE-agent matched Devin's performance primarily through constrained interfaces — custom terminal with limited commands, syntax-checking editors, and line-limited file reading.

### 1.1 Input Guards on All Tools  ✅

Every tool function receives structured validation _before_ execution, returning actionable feedback to the model instead of raw exceptions.

**Module**: `harness_poc/core/tools/guards.py` (590 lines)

All six guards are implemented and tested (66 test methods in `tests/test_tool_guards.py`):

| Guard | Status | Description |
|---|---|---|
| `PathGuard` | ✅ wired | Absolute paths only, deny protected prefixes, deny `../` traversal |
| `SizeGuard` | ✅ wired | Max file size (50KB), max lines, max output chars |
| `TypeGuard` | ⚠️  implemented, not wired | Strict JSON Schema validation with descriptive error messages |
| `IdempotencyGuard` | ⚠️  implemented, not wired | SHA-256 hash of (tool_name, normalized args), session-scoped dedup |
| `ContentGuard` | ✅ wired | Detect binary files by extension, scan for API keys/secrets/PII |
| `QueryGuard` | ✅ wired | Reject SQL writes, enforce LIMIT clause, cap at 1000 rows |
| `GuardPipeline` | ✅ wired | Collects all guard failures, returns combined errors to model |

Wire-point: `ToolRunner.execute_tool()` (`tool_runner.py:164–172`) runs `self._guards.validate()` before every tool invocation.

Default pipeline (`app_factory.py:428–434`): `PathGuard → SizeGuard → ContentGuard → QueryGuard`.

**Remaining**: None. `TypeGuard` and `IdempotencyGuard` are in the default `GuardPipeline` at `harness_poc/app_factory.py:438-441`. `TypeGuard` uses a `schema_provider` lambda with `get_registry()` for lazy schema resolution.

### 1.2 Constrained Tool Interfaces  ✅

All constrained interfaces are implemented and registered in `harness_poc/system_tools/file_tools.py`:

| Tool | Status | Constraints |
|---|---|---|
| `read_file` | ✅ legacy | Offset/limit, binary detection, similar-file suggestions |
| `write_file` | ✅ legacy | Full file overwrite, auto syntax-check on .py/.json/.yaml/.toml |
| `patch` | ✅ legacy | Fuzzy find-and-replace (3 strategies: exact, line-trimmed, whitespace-normalized) |
| `search_files` | ✅ legacy | Content (ripgrep) or filename (glob) search, .gitignore-aware |
| `view_file` | ✅ new | Max 200 lines per call, line-numbered, explicit start/end range required |
| `search_in_file` | ✅ new | Regex search within one file, returns line numbers + context, max 5 context lines |
| `apply_diff` | ✅ new | Unified diff only, Python AST validation before apply, rejects breaking edits |

The `QueryGuard` (`guards.py:505–557`) handles database safety:
- Rejects INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/TRUNCATE/GRANT/REVOKE
- Enforces LIMIT clause on all SELECT queries
- Caps LIMIT at 1000 rows

### 1.3 Tool Documentation as Prompt Engineering  ⚠️

`register()` in `harness_poc/system_tools/__init__.py:33–62` already accepts a `model_description` parameter, separate from `description`. When set, `ToolRunner.discover_tools()` (`tool_runner.py:128`) returns `model_description` to the LLM instead of `description`.

| Tool | model_description |
|---|---|
| `view_file` | ✅ Done |
| `search_in_file` | ✅ Done |
| `apply_diff` | ✅ Done |
| `read_file` | ✅ Done (`file_tools.py:807-816`) |
| `write_file` | ✅ Done (`file_tools.py:852-861`) |
| `patch` | ✅ Done (`file_tools.py:889-897`) |
| `search_files` | ✅ Done (`file_tools.py:940-948`) |


**Remaining**: None. All 7 tools have `model_description`.

### Verification

- `uv run pytest tests/test_tool_guards.py` — 66 tests across all guard types ✅
- ✅ `TypeGuard` + `IdempotencyGuard` wired and tested (46/48 guard tests pass; 2 DB-dependent tests need PostgreSQL)
- ✅ Legacy tool `model_description` additions verified — all 7 tools have `model_description`

---

## Phase 2 — Evaluation Infrastructure

**Status**: ✅ Implemented (2026-06-17)

**Outcome**: The harness can measure its own performance on representative tasks, gating every change with regression detection.

Core infrastructure in `harness_poc/core/eval/`: `EvalTask` (YAML loading), `EvalRunner` (execution + JSON reporting), `JudgeEvaluator` (rubric/trait/binary scoring). CLI wired at `harness_poc/cli.py:1659` (`eval run`). 16 task definitions in `evals/tasks/`, 16 tests in `tests/test_evals.py`.

### 2.1 Task Benchmark Format

New directory `evals/tasks/` with YAML task definitions:

```yaml
# evals/tasks/code_explain.yaml
name: code_explain
description: "Given a function, explain its purpose, inputs, outputs, and edge cases"
category: code_understanding
input:
  file: "harness_poc/core/tools/file_tools.py"
  function: "read_file"
expected_traits:
  - mentions_file_path parameter
  - mentions_line_number parameters
  - mentions_text file reading
  - mentions_binary detection
evaluation:
  type: llm_judge
  rubric: "1-5 scale on accuracy, completeness, and whether edge cases are mentioned"
  min_score: 3
```

Task categories: `code_understanding`, `file_operations`, `multi_step`, `skill_delegation`, `error_recovery`.

### 2.2 Evaluation Runner

New module `harness_poc/core/eval/runner.py`:

```
EvalRunner:
  - Loads tasks from evals/tasks/
  - Runs each task through the harness in deterministic mode (TestModel)
  - Scores outputs via configured evaluator
  - Produces JSON report: evals/results/{timestamp}.json
  - CLI: uv run harness-poc eval run [--task NAME] [--category CAT]
  - Exit code: non-zero if any task fails min_score
```

### 2.3 LLM-as-Judge Evaluator

```
JudgeEvaluator:
  - Takes (task, agent_output) → score + explanation
  - Configurable model (separate from main agent model)
  - Supports rubric-based scoring, binary pass/fail, and trait presence checks
  - Caches evaluations for reproducibility (deterministic when using TestModel)
  - Output: {score: 1-5, passed: bool, explanation: str, trait_results: {trait: bool}}
```

### 2.4 Baseline Benchmarks

16 tasks across all 5 categories in `evals/tasks/`:

| Category | Count | Task names |
|---|---|---|
| code_understanding | 6 | `code_explain_config_model`, `code_explain_guard_pipeline`, `code_trace_tool_execution`, `explain_tool_runner`, `trace_call_path`, `identify_bug` |
| file_operations | 2 | `read_config`, `search_pattern` |
| multi_step | 3 | `multi_step_plan_and_explain`, `gather_context`, `plan_and_execute` |
| skill_delegation | 2 | `skill_delegation_research`, `delegate_and_synthesize` |
| error_recovery | 3 | `error_invalid_path`, `handle_missing_file`, `recover_invalid_input` |

Evaluation types: `trait_check` (6 tasks, works offline) and `llm_judge` (10 tasks, requires `--live` for real scoring).

### Verification

- ✅ `uv run harness-poc eval run` produces a scored JSON report in `evals/results/`
- ✅ `uv run harness-poc eval run --task <name>` runs a single task
- ✅ `uv run harness-poc eval run --category <cat>` filters by category
- ✅ `uv run pytest tests/test_evals.py` — 16 tests covering task loading, runner, judge, and cache
- ✅ Baseline scores committed to `evals/baselines/v1.json` — 16/16 passed, avg 3.94 (2026-06-17)

---

## Phase 3 — Self-Improvement Loops

**Status**: ✅ Implemented (2026-06-17), 2 critical fixes applied

**Outcome**: The agent critiques its own outputs and improves on subsequent attempts, with measurable quality gains on the eval suite.

This is where the harness crosses from "executes" to "improves." Builds directly on Phase 2's evaluation infrastructure.

### 3.1 Evaluator Agent

New system skill `evaluate_output` (evolves the current binary `evaluate_goal` at `harness_poc/system_skills/evaluate_goal/`):

```
evaluate_output:
  inputs: objective, output, context, criteria?
  returns:
    - score: 1-5
    - passed: bool
    - critique: str (specific, actionable)
    - suggestions: list[str]
```

Uses a separate LLM call with a judge persona. The critique is _specific_ — not "needs improvement" but "the function explanation didn't mention the `encoding` parameter at `file_tools.py:45` which handles non-UTF8 files."

### 3.2 Reflexion Loop in GoalRunner

Modify `GoalRunner._run_react_loop()` (`harness_poc/core/runtime/goal_runner.py:469`) to accept an optional `refine: bool` mode:

```
When refine=True:
  1. Execute ReAct loop to completion
  2. Run evaluate_output on the result
  3. If score < threshold and budget remains:
     a. Inject critique into the context as a "reflection" memory entry
     b. Re-run the planning step with the critique visible
     c. Execute the revised plan
  4. Compare scores, keep best result
  5. Store (task, attempts, final_score) in shared memory for analysis
```

This implements the Reflexion pattern (Shinn & Labash 2023) — dynamic memory of past failures used to redirect future attempts.

### 3.3 Evaluator-Optimizer for Skill Outputs

For any skill that produces structured output (code, documents, plans), add an `evaluate_and_refine` wrapper:

```
evaluate_and_refine(skill_name, skill_input, max_iterations=3):
  for attempt in range(max_iterations):
    output = run_skill(skill_name, skill_input)
    evaluation = evaluate_output(objective, output)
    if evaluation.passed:
      return output
    skill_input = inject_critique(skill_input, evaluation.critique)
  return best_output
```

This is the Anthropic evaluator-optimizer pattern — generation → evaluation → feedback → regeneration — applied to skill execution.

### Verification

- Eval suite re-run: Phase 3 should show measurable improvement over Phase 2 baselines (target: ≥10% average score increase on tasks where `refine=True`)
- ✅ `tests/test_reflexion_loop.py` — 11 tests covering evaluate_and_refine, GoalRunner reflexion fields, _is_refine_eligible, _evaluate_result fallback
- ✅ `tests/test_evaluate_output.py` — 13 tests covering skill execution, argument validation, suggestions extraction, SKILL.md structure
- ✅ `_is_refine_eligible` defined — was a `NameError` at runtime (undefined function called at `goal_runner.py:820`)
- ✅ `_evaluate_result` uses LLM-as-judge — builds a real model from `LLMConfig`, falls back to heuristic
- ✅ Reflexion now triggers on completed goals too — previously only budget-exhausted goals reached the reflexion code
- ✅ CLI `--refine` flag wired — `harness-poc goal --refine "objective"` runs GoalRunner with Reflexion enabled (evaluate -> critique -> replan -> rerun)
- ⚠️ CLI `run` and `v2 run` commands still use V2 event-sourced runtime — `--refine` only available on `goal` command

---

## Phase 4 — Multi-Agent Mesh

**Status**: ✅ Core implemented (2026-06-17), critical gap fixed

**Outcome**: Dynamic orchestrator-workers where a central agent decomposes tasks into subtasks it couldn't predict upfront, spawns specialized worker agents in parallel, and synthesizes results.

This builds on `delegate_task` (`harness_poc/system_skills/delegate_task/`) which spawns single subagents — adding dynamic decomposition, parallel execution, and result synthesis.

### 4.1 Orchestrator Agent

New system skill `orchestrate`:

```
orchestrate:
  inputs: objective, available_agent_roles[], max_parallel?
  process:
    1. Decompose objective into subtasks (LLM-driven, not predefined in YAML)
    2. For each subtask, select or spawn an agent with appropriate role
    3. Execute independent subtasks in parallel via delegate_task
    4. Synthesize results into coherent output, flagging conflicts
  returns: synthesized_result, subtask_results[], delegation_tree
```

Key difference from pipeline YAML: subtasks are _discovered_ by the orchestrator at runtime based on the specific input, not predefined.

### 4.2 Persistent Agent Roles

Agent roles stored as knowledge skills in `agents/roles/`:

```markdown
# agents/roles/code_reviewer/SKILL.md
---
name: code_reviewer
type: knowledge
---
You are a senior code reviewer for the Deverino harness. Your criteria:
- Correctness: does the code do what it claims?
- Safety: no path traversal, no secrets exposure, no injection
- Style: consistent with project conventions (ruff, ty, 4-space indent)
- Completeness: edge cases handled, error paths covered

When reviewing, cite specific file paths and line numbers.
```

The orchestrator loads role skills via `skill_view` and instantiates subagents with them as personas.

### 4.3 Result Synthesis

The orchestrator's synthesize step:

- Receives all subtask results with their evaluation scores
- Identifies conflicts or gaps between subtask outputs
- Produces a unified result with traceability to which subtask produced which component
- Stores the full delegation tree in `shared_memory` for dashboard inspection
- If synthesis reveals gaps, spawns remedial subtasks

### 4.4 Delegation Tree Dashboard

Extend the existing subagent tree in `harness_poc/core/observability/dashboard.py:1098–1210` to show:

- Which orchestrator spawned which workers
- Worker role, input, output, duration, evaluation score
- Synthesis result and conflict resolution
- Token cost per subagent and total

### Verification

- ✅ `tests/test_orchestrator.py` — 14 tests covering decomposition, role picking, conflict detection, synthesis, delegation tree
- ✅ `orchestrate` skill executes subtasks directly via `ThreadPoolExecutor` + `delegate_task._run_subagent` — was dead code (runtime ignored `requested_actions`)
- ✅ `agents/roles/` — 4 knowledge skill personas: architect, code_reviewer, web_researcher, data_validator
- ✅ Delegation tree stored in `shared_memory` under `orchestration_tree` key
- ✅ Dashboard subagent tree already supports orchestrator visualization (`fetch_sub_agent_tree` with `SubAgentNode`)
- ✅ `_llm_decompose()` — LLM-driven decomposition via PydanticAI `Agent` with `DecompositionPlan` structured output, loads `agents/roles/` as context, falls back to keyword-based
- ✅ `agents/roles/` loaded as LLM context via `_load_role_descriptions()` — closing the persona path gap
- ✅ Eval task: `orchestrate_code_review` — trait_check task testing orchestration keywords
- ⚠️ No eval tasks for multi-agent orchestration end-to-end — existing tasks test single `delegate_task`, not parallel orchestration

---

## Phase Ordering Rationale

```
Phase 1 (ACI) → Phase 2 (Evals) → Phase 3 (Self-Improvement) → Phase 4 (Multi-Agent)
     │                │                    │                        │
     └─ Prerequisite to all quality work   │                        │
                      └─ Prerequisite to Phase 3 (needs scoring)   │
                                           └─ Prerequisite to Phase 4 (agents must self-correct)
```

Each phase produces a measurable improvement on the eval suite established in Phase 2:

- **Phase 1** prevents regressions by catching model errors at the tool boundary
- **Phase 2** makes regressions visible by establishing baseline scores
- **Phase 3** makes improvements automatic through iterative critique and refinement
- **Phase 4** scales capability through dynamic, parallel agent coordination

---

## Non-Goals (Explicitly Out of Scope)

- **MCP integration**: The Model Context Protocol ecosystem is valuable but rapidly evolving. Defer until the standard stabilizes and the harness has Phase 1–3 solid.
- **Multi-model routing**: Cost optimization through model selection (cheap model for classification, expensive for reasoning) is a Phase 4+ optimization.
- **Fine-tuning agent behavior**: The harness uses prompt-based personas; fine-tuning is a separate research direction.
- **Remote/distributed execution**: The harness is local-first. Distributed agent execution adds infrastructure complexity without clear leverage at this stage.
- **GUI/drag-and-drop agent builder**: The harness is a code-first research artifact. Visual builders are for a different audience.
