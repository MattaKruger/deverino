---
name: deverino-react-acdl
type: knowledge
description: ACDL specification for the Deverino agent harness ReAct loop. Describes the streaming tool-augmented loop, layered system prompt assembly (SOUL + STATE + context_map + skill_catalog + tool_policy), history truncation, and the autonomous goal variant.
auto_invokable: false
---

# Deverino ReAct Loop — ACDL Specification

This knowledge skill captures the ACDL spec for the Deverino harness agent loop. The spec file lives at `/scratch/deverino_react.acdl` and describes two prompt variants:

## 1. `DeverinoChatLoop[@T]` — Interactive chat

The primary chat loop in `pydantic_runtime.py`. Key characteristics:

- **Namespace `env`**: `user_input`, `retrieved_chunks`, `web_results`, `codebase_matches`, `tool_results`, `memory_hits`
- **Namespace `sys`**: `soul_charter` (SOUL.md), `project_state`, `session_state`, `context_map` (PEEK), `available_skills`, `tool_policy`, config values
- **Namespace `resp`**: `answer`, `reasoning`, `tool_calls`, `observations`, `token_usage` per turn
- **S block** (system context): 5-layer concatenation — SoulCharter, StateBlock, ContextMapBlock (conditional), SkillCatalogBlock, ToolPolicyBlock
- **U block** (turns): Last 6 turns via `ConversationTurn[@t]` fragment, then current `env.user_input[@T]`
- **Fragments**: `SoulCharter`, `StateBlock`, `ContextMapBlock`, `SkillCatalogBlock`, `ToolPolicyBlock`, `ConversationTurn[@t]`, `ToolBudgetBlock`, `TruncationPolicy`
- **Tool budget**: Max 10 consecutive tool rounds, 3 semble_search calls per run, per-tool dedup
- **History truncation**: Drop oldest, no summarization, budget 24000 tokens / 6 recent turns

## 2. `DeverinoGoalLoop[@T, $max_iterations]` — Autonomous goal

The goal runner variant in `goal_runner.py`. Wraps the same ReAct loop in explicit iteration budget with structured evaluation:

- **Adds `env.goal_objective`**, `env.max_iterations`, `env.max_tokens`, `env.max_seconds`
- **Adds `sys.event_history`** — typed `BaseEvent` instances mapped via `EventMappedTurn` fragment
- **Adds `resp.is_complete`**, `resp.final_answer` for termination
- **`GoalHeader` fragment** shows objective and budget
- **Autonomous Loop Policy**: evaluate after each cycle, `is_complete=true` halts, cap at 10 consecutive tool rounds
- **Event mapping**: `SkillCalled` → `assistant: [Action]`, `SkillCompleted` → `user: [Observation]`, `GoalEvaluated` → `user: [evaluate_goal]` (mirrors `_event_to_message()` in goal_runner.py)

## Fact annotations (semantic metadata)

```acdl
Fact: {
    "react_style": "streaming_tool_loop"
    "framework": "pydantic_ai"
    "end_strategy": "early"
    "max_consecutive_tool_rounds": 10
    "history_truncation": "drop_oldest"
    "tool_call_deduplication": "per_run"
    "context_assembly": "layered_concatenation"
    "context_map_provenance": "event_sourced_peek"
    "event_schema": "typed_pydantic_BaseEvent"
}
```

## Architecture traceability

Each ACDL construct maps to a specific Python source:

| ACDL construct                            | Source file                            | Line(s)                                                |
| ----------------------------------------- | -------------------------------------- | ------------------------------------------------------ |
| `sys.soul_charter`                        | `harness_poc/system_prompts/SOUL.md`   | entire file                                            |
| `sys.project_state` + `sys.session_state` | `harness_poc/core/state.py`            | `build_state_context()`                                |
| `sys.context_map`                         | `harness_poc/app_factory.py`           | 118-124                                                |
| `sys.available_skills`                    | `harness_poc/core/skill_catalog.py`    | `build_skill_catalog()`                                |
| `sys.tool_policy`                         | `harness_poc/core/pydantic_runtime.py` | `_with_tool_policy()`                                  |
| `env.user_input[@T]` + `ConversationTurn` | `harness_poc/core/pydantic_runtime.py` | `_stream_text_async()`                                 |
| Tool budget cap                           | `harness_poc/core/pydantic_runtime.py` | 98 (`max_consecutive_tool_rounds = 10`)                |
| Goal loop variant                         | `harness_poc/core/goal_runner.py`      | `run_goal()`, `_event_to_message()`                    |
| History truncation config                 | `harness.yaml`                         | `chat_history_max_tokens`, `chat_history_recent_turns` |
