# PydanticAI Migration Implementation Plan

Created: 2026-05-18 21:03:20 Europe/Brussels

## Goal

Move the harness from a hand-rolled OpenAI-compatible tool loop to PydanticAI while preserving the parts that already work well:

- SQLite blackboard state and memory.
- `SKILL.md` skill discovery.
- In-process `SkillContext` / `SkillResult` skill execution.
- Deterministic YAML workflows.
- REPL and Typer command surface.

The migration should be incremental. The first working slice should introduce PydanticAI beside the existing `LLMClient`, then move one runtime path at a time.

## Current Runtime Shape

The current agent runtime is split across:

- `harness_poc/core/llm_client.py`
  - DeepSeek/OpenAI-compatible chat client.
  - Manual tool-call parsing.
  - Manual streaming response parsing.
  - Mock fallback behavior.
  - Token usage extraction.
- `harness_poc/core/goal_runner.py`
  - Manual ReAct loop.
  - Event history formatting.
  - Tool execution.
  - `evaluate_goal` interception.
  - Stuck detection and budget checks.
- `harness_poc/core/skill_runner.py`
  - Discovers `SKILL.md` files.
  - Converts skill metadata to OpenAI tool schemas.
  - Executes skill entrypoints.
- `harness_poc/repl.py`
  - Maintains `app_state.messages`.
  - Sends chat input to `LLMClient.stream_chat`.
  - Executes one model-requested tool.
  - Runs a second model call after tool execution.

## PydanticAI Fit

Based on current PydanticAI v1 docs:

- Use `Agent` for primary and sub-agent runtimes.
- Use `deps_type` and `RunContext` to pass `session_id`, `database`, `config`, and `skill_runner`.
- Use `Tool.from_schema` to reuse existing `SKILL.md` JSON schemas without rewriting every skill as a typed Python function.
- Use `OpenAIChatModel` with `DeepSeekProvider` for DeepSeek, or `OpenAIProvider` with a custom `base_url` for generic OpenAI-compatible providers.
- Use `output_type` for structured results such as delegated research output and goal completion decisions.
- Use PydanticAI message history once the REPL path is migrated.
- Use PydanticAI test/function models to replace custom `LLMClient` mocks.

## Reuse vs Rewrite

### Reuse

- `BlackboardDatabase` and all current state/memory tables.
- `SkillContext`, `SkillResult`, and skill plugin entrypoint contract.
- `SkillRunner.parse_skill_document`.
- `SkillRunner.execute_skill`.
- Existing `SKILL.md` frontmatter schemas.
- Existing system and project skill implementations, except direct `LLMClient` usage inside skills.
- `WorkflowRunner`.
- CLI command groups and direct `/skill` execution.

### Rewrite or Adapt

- Replace `LLMClient` with a PydanticAI runtime facade.
- Replace OpenAI-style tool schema generation with PydanticAI `Tool.from_schema` tool registration.
- Replace `GoalRunner`'s manual model loop with a PydanticAI-backed loop or agent wrapper.
- Replace `delegate_task`'s direct `LLMClient().chat(...)` call with a PydanticAI sub-agent.
- Replace custom model mocks with PydanticAI test/function models.
- Adapt REPL chat history from `list[Message]` to PydanticAI `ModelMessage` history after the goal path is stable.

## Design Constraints

1. Do not rewrite skill plugins just to satisfy PydanticAI. The skill contract is a core repo feature.
2. Keep deterministic workflows independent of PydanticAI. Workflow states call skills directly, not through an LLM.
3. Preserve human-in-loop skill behavior. A skill returning `needs_orchestrator_action` must still stop and surface its prompt to the user.
4. Keep mock/test mode deterministic and API-key-free.
5. Maintain support for DeepSeek as the default configured provider.
6. Keep each phase shippable with focused tests.

## Proposed Architecture

Add a new runtime module:

```text
harness_poc/core/pydantic_runtime.py
```

Core types:

```python
@dataclass(frozen=True, slots=True)
class AgentDeps:
    session_id: str
    database: BlackboardDatabase
    config: HarnessConfig
    skill_runner: SkillRunner


@dataclass(frozen=True, slots=True)
class AgentRunResult:
    content: str
    usage: Usage | None = None
    messages: list[ModelMessage] = field(default_factory=list)
```

Runtime responsibilities:

- Build the configured PydanticAI model.
- Build a primary `Agent[AgentDeps]`.
- Convert discovered skills into PydanticAI tools.
- Execute skill tools through `SkillRunner`.
- Provide sync wrappers for current CLI/REPL code.

## Phase 1: Dependency and Runtime Skeleton

### 1a. Add Dependency

Add `pydantic-ai` to `pyproject.toml`.

Keep `openai` temporarily until all direct `LLMClient` paths are removed.

### 1b. Add Provider Factory

Create a model factory in `pydantic_runtime.py`:

- Load existing `DeepSeekSettings` initially, or move provider settings into a neutral settings class.
- If `DEEPSEEK_API_KEY` is set, build:

```python
OpenAIChatModel(
    settings.model,
    provider=DeepSeekProvider(api_key=settings.api_key),
)
```

- If a generic OpenAI-compatible base URL is configured later, use `OpenAIProvider(base_url=..., api_key=...)`.
- If no API key is present, use a deterministic test/function model for local tests.

### 1c. Tests

Add tests for:

- Runtime can be constructed without API keys.
- Provider factory selects mock/test mode when credentials are absent.
- Existing app startup still works.

## Phase 2: Skill-to-PydanticAI Tool Adapter

### 2a. Convert Existing Skill Schemas

Add a function:

```python
def build_skill_tools(skill_runner: SkillRunner) -> list[Tool[AgentDeps]]:
    ...
```

For each `SKILL.md`, create a `Tool.from_schema`:

```python
Tool.from_schema(
    function=_execute_skill_tool,
    name=skill_name,
    description=description,
    json_schema=parameters,
    takes_ctx=True,
)
```

The wrapper should:

- Pull `session_id` and `skill_runner` from `ctx.deps`.
- Execute the resolved skill.
- Return a compact string or JSON object with `status`, `content`, `artifacts`, and `requested_actions`.
- Preserve aliases currently handled in `SkillRunner`.

### 2b. Human-in-Loop Handling

For `SkillResult.status == "needs_orchestrator_action"`:

- Return a structured marker in the tool result.
- Instruct the primary agent that this status means it must stop and surface the prompt unchanged.

This is a compatibility requirement because the current REPL relies on this behavior for flows such as `spec_writer` gather mode.

### 2c. Tests

Add tests for:

- A discovered skill becomes a PydanticAI tool with the same name and JSON schema.
- Tool execution calls `SkillRunner.execute_skill`.
- `needs_orchestrator_action` is represented clearly in the returned tool result.

## Phase 3: PydanticAI Runtime Facade

### 3a. Add Primary Agent Builder

Add:

```python
def build_primary_agent(system_prompt: str, tools: list[Tool[AgentDeps]]) -> Agent[AgentDeps]:
    ...
```

The prompt should include:

- Existing `SOUL.md`.
- Current project/session state context.
- Tool result policy.
- Human-in-loop stop policy.

### 3b. Add Compatibility Methods

Initially expose methods close to current usage:

```python
def run_text(self, prompt: str, *, deps: AgentDeps, message_history: list[ModelMessage]) -> AgentRunResult:
    ...

def stream_text(...):
    ...
```

Do not delete `LLMClient` yet. The app can carry both runtimes during migration.

### 3c. AppState Wiring

Update `AppState` to optionally hold:

```python
pydantic_runtime: PydanticAgentRuntime | None
pydantic_messages: list[ModelMessage]
```

Keep `llm_client`, `messages`, and `tools` until the old REPL and goal paths are migrated.

### 3d. Tests

Add tests for:

- `build_app_state()` initializes the Pydantic runtime.
- Runtime can answer through test model without network.
- Existing CLI tests still pass.

## Phase 4: Migrate `delegate_task`

### 4a. Define Structured Output

Create a Pydantic model:

```python
class DelegatedTaskOutput(BaseModel):
    status: Literal["completed", "failed", "blocked"] = "completed"
    summary: str
    artifacts: dict[str, Any] = Field(default_factory=dict)
```

### 4b. Replace Direct `LLMClient`

In `harness_poc/system_skills/delegate_task/skill.py`:

- Build a PydanticAI sub-agent using the persona template as system prompt.
- Use `output_type=DelegatedTaskOutput`.
- Run with objective and context.
- Store validated output in blackboard exactly as today.

### 4c. Tests

Update `delegate_task` tests or add focused coverage:

- Works without API key using deterministic test model.
- Writes memory under the requested key.
- Preserves result artifact shape.

## Phase 5: Migrate Goal Runner

### 5a. Decide Completion Shape

Prefer structured output over a normal `evaluate_goal` skill for the final completion decision:

```python
class GoalDecision(BaseModel):
    is_complete: bool
    reasoning: str
```

However, keep `evaluate_goal` compatibility until tests show the structured output path is stable.

### 5b. Replace Model Call Path

Change `GoalRunner.run` to use PydanticAI for model decisions and tool execution.

Keep these existing `GoalRunner` responsibilities:

- Iteration budget.
- Optional wall-clock budget.
- Optional token budget if reliable usage is available.
- Database event recording.
- Stuck detection.
- Final `GoalRunResult` shape.

Remove or shrink these responsibilities:

- Manual OpenAI message formatting.
- Manual tool-call parsing.
- Manual synthetic tool result message construction.

### 5c. Event Recording

Record events from the PydanticAI run:

- Tool calls become `llm_action` events.
- Tool returns become `tool_observation` events.
- Final structured completion becomes an `evaluate_goal` observation for compatibility with existing audit/history views.

If PydanticAI does not expose the exact intermediate event shape needed, keep the skill-tool wrapper responsible for recording execution observations.

### 5d. Tests

Update `tests/test_goal_runner.py`:

- Completes when structured decision says complete.
- Continues when decision says incomplete.
- Executes a skill tool through the adapter.
- Blocks repeated identical actions.
- Enforces iteration budget.
- Enforces time/token budget where applicable.

## Phase 6: Migrate REPL Chat

### 6a. Replace `app_state.messages`

Move REPL chat history to PydanticAI `ModelMessage` objects:

- Load system prompt through the agent, not as a raw message in `app_state.messages`.
- Keep only `pydantic_messages` as the durable in-process chat history.
- Use `result.new_messages()` / equivalent PydanticAI history APIs after each turn.

### 6b. Streaming

Replace `LLMClient.stream_chat` with PydanticAI streaming:

- Stream text chunks to `_print_stream_chunk`.
- Capture usage from the final result.
- Preserve the current token prompt bar if reliable usage fields are available.

### 6c. Human-in-Loop Stop

When a skill returns `needs_orchestrator_action`, the REPL must:

- Print the skill content directly.
- Not ask the model for a second summarizing response.
- Preserve enough context for the user answer to become the next model turn.

This is the main behavioral risk in the REPL migration.

### 6d. Tests

Update tests for:

- Normal chat response.
- Tool execution response.
- `needs_orchestrator_action` surfaces directly.
- Existing `/skill`, `/state`, `/workflow`, and completion tests still pass.

## Phase 7: Cleanup Old Runtime

Once `delegate_task`, `GoalRunner`, and REPL chat are migrated:

- Delete or deprecate `harness_poc/core/llm_client.py`.
- Remove direct OpenAI SDK usage if no longer needed.
- Remove old `Message`, `LLMResponse`, and manual `Usage` types unless still useful as compatibility aliases.
- Update README architecture diagram.
- Update docs that mention OpenAI tool schemas as the active runtime contract.

## Test Plan

Run after each phase:

```bash
uv run pytest
uv run ruff check .
uv run ty check
```

Focused suites during development:

```bash
uv run pytest tests/test_goal_runner.py
uv run pytest tests/test_repl_skill_execution.py
uv run pytest tests/test_cli.py
```

## Acceptance Criteria

- Existing deterministic workflows still run through `WorkflowRunner`.
- Existing skills are discoverable and executable directly.
- Existing `SKILL.md` schemas are reused as PydanticAI tools.
- `delegate_task` no longer imports or instantiates `LLMClient`.
- `GoalRunner` no longer manually parses provider tool calls.
- REPL chat uses PydanticAI message history and streaming.
- Test suite passes without real model credentials.
- DeepSeek remains supported through PydanticAI provider configuration.

## Risks and Mitigations

### Risk: Human-in-loop behavior is lost

PydanticAI normally continues after tool execution. The current harness sometimes needs to stop immediately and ask the user a question.

Mitigation: encode `needs_orchestrator_action` as a first-class tool result policy and test it before migrating REPL chat.

### Risk: Dynamic skills are awkward to expose as tools

PydanticAI works best with typed Python functions, while this harness has dynamic skill schemas in markdown frontmatter.

Mitigation: use `Tool.from_schema` so `SKILL.md` remains the source of truth.

### Risk: Test mocks become harder

The current `LLMClient` mock is simple and local.

Mitigation: introduce deterministic PydanticAI test/function models in Phase 1 before changing behavior.

### Risk: Provider settings drift

The repo currently has `DeepSeekSettings` embedded in `llm_client.py`.

Mitigation: move provider settings to a neutral config module during Phase 1 or Phase 3, then delete the old settings only in cleanup.

## Recommended First Slice

Implement Phases 1 and 2 together:

1. Add `pydantic-ai`.
2. Add `pydantic_runtime.py`.
3. Build PydanticAI tools from existing `SKILL.md` schemas.
4. Prove one skill executes through the PydanticAI adapter in tests.

This validates the core migration bet without touching REPL chat, goal loops, or workflows.
