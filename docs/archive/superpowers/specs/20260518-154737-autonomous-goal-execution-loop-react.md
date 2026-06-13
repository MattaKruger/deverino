# Autonomous Goal Execution Loop (ReAct)

## Objective

Implement an autonomous ReAct execution loop triggered by /goal <objective>. The loop runs until a verifiable stopping condition is met, a budget is exhausted, or an irrecoverable error occurs.

## Background

Current harness: Python 3.12+, Typer/Rich CLI, REPL (prompt_toolkit), SQLite blackboard (state_events table with event sourcing), SkillRunner with system_skills/ and project_skills/, LLMClient for model calls. Currently single prompt-response roundtrip only. Engine/workspace split V1.1. Container lifecycle managed by workflow runner (spawn/exec/destroy). State consolidation with preview/propose/approve.

## Requirements

- 1. Database: extend state_events with llm_action and tool_observation event types; add retrieval of N most recent events per session for context window construction. 2. GoalRunner core class in harness_poc/core/goal_runner.py managing while True loop, injecting persistent system prompt binding agent to objective, handling LLMClient/SkillRunner handoff, writing both steps to DB. 3. evaluate_goal system skill at harness_poc/system_skills/evaluate_goal/ with schema {is_complete: bool, reasoning: str}. GoalRunner intercepts calls — if is_complete=true break loop, if false append reasoning as observation and continue. 4. Stuck detection: rolling hash of last 3 (tool_name, args) pairs; block 4th identical attempt, inject synthetic tool_observation error. 5. REPL: parse > /goal <objective> syntax. 6. CLI: add @app.command("goal").

## Non-Goals

- Multi-agent collaboration (single primary agent only). Chained workflows (this is a loop, not a DAG). Streaming responses. Persistent loop state across harness restarts (session-scoped only).

## Proposed Behavior

- Add or change the smallest coherent surface that satisfies the objective.
- Respect these constraints: - Python 3.12+ typing (| union operators). No LangChain, LlamaIndex, AutoGen, or external orchestration frameworks. Standard library + existing LLMClient + SQLite only. Database init must remain idempotent (CREATE TABLE IF NOT EXISTS).
- Preserve discoverability, testability, and existing command behavior.

## Acceptance Criteria

- The requested behavior is available through the expected user path.
- Errors and unclear input produce actionable feedback.
- Existing related tests continue to pass.

## Test Plan

- Add focused unit tests for success and unclear-input paths.
- Run the targeted pytest file for the changed behavior.
- Run lint/type checks if shared interfaces changed.

## Open Questions

- 1. Budget mechanism: token-based, iteration count, wall-clock time, or a combination? 2. Context window management: sliding window over events, summarization, or both? 3. Should the evaluate_goal skill be callable by the agent at any time, or only after at least one action? 4. What is the max loop iteration before a hard circuit breaker trips (independent of stuck detection)?
