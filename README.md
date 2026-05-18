# Deverino

A Python 3.12 proof-of-concept for autonomous LLM agent workflows. It provides an interactive REPL, a CLI goal runner, and a typed event-driven architecture where agents publish lifecycle events to a shared bus — enabling multi-agent coordination, structured observability, and future async upgrades without rewriting callers.

## Quickstart

```bash
# Start the interactive REPL
uv run harness-poc

# Run an autonomous goal
uv run harness-poc goal "Write a one-sentence summary of the ReAct prompting pattern" --max-iterations 5

# Run a workflow
uv run harness-poc workflow run research_task "What is the ReAct prompting pattern?"

# List available skills
uv run harness-poc skill list
```

Set your LLM credentials before starting:

```bash
export OPENAI_API_KEY=sk-...
# or for DeepSeek
export OPENAI_BASE_URL=https://api.deepseek.com
export OPENAI_API_KEY=sk-...
```

## Architecture

```
harness_poc/
├── cli.py                  # Typer CLI entry point
├── repl.py                 # Interactive REPL with tab completion
├── app_factory.py          # Wires DB, EventBus, LLM client, skills, workflows into AppState
├── core/
│   ├── database.py         # BlackboardDatabase — SQLite-backed session/memory/state tables
│   ├── events.py           # Typed Pydantic event hierarchy with EVENT_REGISTRY
│   ├── event_store.py      # SQLite persistence for events — owns the state_events table
│   ├── event_bus.py        # In-process pub/sub — dispatches to subscribers, persists via EventStore
│   ├── goal_runner.py      # Autonomous ReAct loop — publishes events via EventBus
│   ├── llm_client.py       # OpenAI-compatible client
│   ├── pydantic_runtime.py # PydanticAI agent runtime with tool-based skill execution
│   ├── skill_runner.py     # Discovers and executes skills from SKILL.md + skill.py
│   ├── state.py            # StatePayload, StateProposal, state context builder
│   ├── config.py           # HarnessConfig from harness.yaml
│   └── workflow_runner.py  # Executes YAML workflow state machines
├── system_skills/          # Built-in skills (evaluate_goal, delegate_task, etc.)
└── system_prompts/         # SOUL.md — system prompt for the primary agent
skills/                     # Project-local skills (spec_writer, web_search, etc.)
workflows/                  # YAML workflow definitions
personas/                   # Prompt templates for sub-agents
```

### Event-Driven Architecture

All agent lifecycle events flow through a typed, Pydantic-based event bus. This replaces the previous pattern of direct `BlackboardDatabase` method calls (`record_llm_action`, `record_tool_observation`, `get_recent_events`) with a structured pub/sub system that is the foundation for multi-agent coordination, observability, and future async upgrades.

**Event hierarchy** (`core/events.py`):

| Event                | Published when                                     |
| -------------------- | -------------------------------------------------- |
| `AgentStarted`       | A `GoalRunner.run()` loop begins                   |
| `SkillCalled`        | A skill is about to be executed                    |
| `SkillCompleted`     | A skill finishes (`success` / `error` / `blocked`) |
| `GoalEvaluated`      | The LLM calls `evaluate_goal` to assess completion |
| `LLMTextEmitted`     | The LLM emits text without a tool call             |
| `SubAgentDispatched` | A sub-agent is spawned (defined, wiring follow-up) |
| `SubAgentCompleted`  | A sub-agent finishes (defined, wiring follow-up)   |

Each event is a Pydantic `BaseModel` with `event_id`, `session_id`, `created_at`, plus type-specific fields (e.g. `goal: str` on `AgentStarted`, `tool_name` + `arguments` on `SkillCalled`). A `EVENT_REGISTRY: dict[str, type[BaseEvent]]` maps type names to classes so deserialization never needs `if/elif` chains.

**Storage** (`core/event_store.py`):

`EventStore` persists events to the existing `state_events` SQLite table using the format `{"event_type": "SkillCalled", "payload": {...}}`. During retrieval, rows are deserialized through `EVENT_REGISTRY` into typed Pydantic objects. Corrupted or legacy rows are skipped with a warning — they don't crash context window builds. `BlackboardDatabase` no longer writes to `state_events`; `EventStore` now fully owns that table (proposal state-change events are written with direct inlined INSERTs).

**Pub/sub** (`core/event_bus.py`):

```python
class EventBus:
    def publish(self, event: BaseEvent) -> None:
        # 1. Persist to EventStore (hard failure if this fails)
        # 2. Dispatch to registered subscribers synchronously
        # 3. Catch subscriber exceptions individually — log, continue

    def subscribe(self, event_type: type[E], handler: Callable[[E], None]) -> None: ...

    def get_recent_events(
        self, session_id: str, limit: int = 20,
        event_types: list[type[BaseEvent]] | None = None,
    ) -> list[BaseEvent]: ...
```

Subscribers register by event type. A failing handler never blocks other handlers. The synchronous dispatch loop can be swapped for `asyncio.create_task()` later without changing any callers.

**Data flow in a GoalRunner loop**:

```
GoalRunner.run(goal, app_state)
  ├─ bus.publish(AgentStarted(session_id, goal))
  │
  └─ [each iteration]
       ├─ bus.get_recent_events(session_id, limit=20,
       │       event_types=[SkillCalled, SkillCompleted, GoalEvaluated, LLMTextEmitted])
       ├─ _build_messages(goal, events)       # events → formatted context window
       ├─ _decide_next_action(...)            # PydanticAI structured decision
       │
       ├─ [tool call path]
       │    ├─ bus.publish(SkillCalled(tool_name, arguments))
       │    ├─ skill_runner.execute_skill(...)
       │    └─ bus.publish(SkillCompleted(tool_name, status, content, artifacts))
       │
       ├─ [evaluate_goal intercept]
       │    └─ bus.publish(GoalEvaluated(is_complete, reasoning, final_answer))
       │
       └─ [_llm_text path]
            └─ bus.publish(LLMTextEmitted(content))
```

**Testing** (`tests/test_event_bus.py`, `tests/test_event_store.py`):

- `EventStore` tests use temp-file SQLite — no mocking, real round-trips
- `RecordingEventBus` (in `tests/helpers.py`) collects events in memory, no persistence — used in `test_goal_runner.py` to assert event sequences without disk I/O
- Full integration: `GoalRunner` with real `EventBus` + `EventStore`, verifying typed event retrieval after completed goal loops

### The blackboard

The **blackboard** (`harness_poc/blackboard.db`) is the shared state store. Skills read and write to it by session key. State is split into two layers: ephemeral session state and durable project state, with an explicit proposal/approval step to promote session facts to project state.

### Skills

Skills are discovered at startup by scanning `harness_poc/system_skills/` and `skills/`. Each skill is a directory containing `SKILL.md` (metadata + parameter schema) and `skill.py` (an `execute(ctx, arguments) -> SkillResult` function). Skills with `auto_invokable: true` in their frontmatter are registered as PydanticAI tools so the LLM can invoke them autonomously during goal runs.

### GoalRunner

`GoalRunner` (`core/goal_runner.py`) runs an autonomous ReAct loop: build context → LLM decides next action → execute → publish events → repeat. It supports:

- **Stuck detection**: identical (tool, args) repeated N times → injects a `blocked` `SkillCompleted` event
- **Budget enforcement**: max iterations, max tokens (tiktoken estimate), max wall-clock seconds
- **Streaming progress**: optional `on_text` callback for TUI/CLI progress display
- **`evaluate_goal` interception**: the LLM's self-evaluation is intercepted and not executed as a tool — the runner determines completion from the structured decision

## The REPL

`uv run harness-poc` starts an interactive session. Type a message and the agent responds, calling skills as tools when needed.

### Built-in REPL commands

```
/skill list                          # list all skills
/skill show <name>                   # print a skill's SKILL.md
/skill <name> <args>                 # call a skill directly (bypasses LLM)
/skill <name> {"key": "value"}       # call with JSON arguments
/state show [project|session|all]    # inspect blackboard state
/state consolidate [preview|propose|approve]
/help
/exit
```

### Calling skills directly

Skills accept arguments as JSON, key=value pairs, or a bare string (mapped to the skill's primary parameter):

```
> /skill spec_writer {"mode": "gather", "gather_key": "my_spec"}
> /skill spec_writer mode=questions goal="Add export support"
> /skill read_memory research_result
```

## CLI Commands

```bash
# Autonomous goal execution
uv run harness-poc goal "Search the web for the capital of France" --max-iterations 5

# Goal with streaming progress
uv run harness-poc goal "Summarize the event-driven architecture" --max-iterations 10 --max-tokens 8000

# State management
uv run harness-poc state show project    # durable project state
uv run harness-poc state show session    # ephemeral session state
```

## Skills

### Auto-invokable skills (LLM can call directly)

| Skill              | Description                                             |
| ------------------ | ------------------------------------------------------- |
| `web_search`       | Search the web via LangSearch API                       |
| `semble_search`    | Semantic codebase search — find code by describing it   |
| `read_memory`      | Read a key from the blackboard for the current session  |
| `summarize_memory` | Summarise a blackboard memory key into a compact result |
| `review_work`      | Review the current working tree                         |

### Other system skills

| Skill               | Description                                                                   |
| ------------------- | ----------------------------------------------------------------------------- |
| `delegate_task`     | Spawns an isolated LLM sub-agent with a persona to handle a sub-task          |
| `evaluate_goal`     | GoalRunner intercept — LLM signals completion/blockage with reasoning         |
| `consolidate_state` | Promotes session state to durable project state (preview / propose / approve) |
| `container_spawn`   | Creates a detached Docker/Podman container for the session                    |
| `container_exec`    | Runs a shell command inside an existing container                             |
| `container_destroy` | Stops and removes a container                                                 |

### Project skills

| Skill               | Description                                                            |
| ------------------- | ---------------------------------------------------------------------- |
| `spec_writer`       | Multi-turn Q&A that produces structured XML context and markdown specs |
| `reflect_on_result` | Assesses whether a sub-agent result satisfies the original objective   |

## Writing specs with spec_writer

`spec_writer` has a two-phase flow for producing implementation-ready technical specs.

### Phase 1 — gather (collect requirements)

`gather` mode runs a multi-turn Q&A loop, asking one question at a time:

1. Project overview (tech stack, architecture)
2. Feature request (user intent)
3. Component names (as a list)
4. Per-component detail — one question per component, loops until all are answered
5. Constraints

When all phases are complete, it writes a structured XML context document to `specs/` and stores it in the blackboard.

**Via the LLM (recommended)** — just describe what you want and let the agent drive:

```
> I want to write a spec for <feature>. Use spec_writer in gather mode.
```

The agent calls `spec_writer` with `mode=gather`, presents each question to you, and passes your answers back as the `answer` argument on the next call.

**Directly** — call the skill yourself, passing each answer manually:

```
# First call — no answer yet
> /skill spec_writer {"mode": "gather", "gather_key": "my_spec"}

# Subsequent calls — pass your answer to the previous question
> /skill spec_writer {"mode": "gather", "gather_key": "my_spec", "answer": "A Python LLM harness backed by SQLite."}
```

Use the same `gather_key` across REPL restarts — state is persisted in the blackboard.

### Phase 2 — draft (generate the spec)

Once gather is complete, draft mode feeds the XML context to the LLM and produces a markdown spec:

```
> /skill spec_writer {"mode": "draft", "gather_key": "my_spec", "use_llm": true}
```

Or without a prior gather session, using flat inputs:

```
> /skill spec_writer {"mode": "draft", "goal": "Add export support", "context": "...", "requirements": "...", "use_llm": true}
```

The spec is written to `specs/` and stored in the blackboard under `output_key` (default: `spec_writer_result`).

## Workflows

Workflows are YAML state machines in `workflows/`. Each state calls a skill and passes its output to the next state via template variables.

```bash
uv run harness-poc workflow run research_task "What is the ReAct pattern?"
uv run harness-poc workflow run research_plan_execute "Summarise the codebase"
```

A workflow definition looks like:

```yaml
name: research_task
states:
  delegate:
    skill: delegate_task
    args:
      persona: web_researcher
      objective: "{{ inputs.objective }}"
      memory_key: research_result
    next: reflect
  reflect:
    skill: reflect_on_result
    args:
      objective: "{{ inputs.objective }}"
      memory_key: "{{ states.delegate.artifacts.memory_key }}"
    next: done
  done:
    terminal: true
```

## Configuration

`harness.yaml` at the repo root controls paths and runtime settings. The database is local to the repo (`harness_poc/blackboard.db`) and should not be committed.

## Development

```bash
uv run pytest                  # full test suite (87 tests)
uv run pytest tests/test_goal_runner.py -v  # goal runner + event bus integration
uv run pytest tests/test_event_bus.py tests/test_event_store.py -v  # event system
uv run ruff check .            # lint
uv run ty check                # type check
uv run harness-poc skill create <name> "<description>"  # scaffold a new skill
```

Skills follow the `execute(ctx: SkillContext, arguments: dict[str, Any]) -> SkillResult` contract. See any skill in `skills/` or `harness_poc/system_skills/` for a working example.
