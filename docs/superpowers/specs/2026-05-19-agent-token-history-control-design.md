# Agent Token History Control - Implementation Spec

**Date:** 2026-05-19
**Status:** Draft

## Objective

Prevent interactive agent runs from repeatedly resending oversized historical tool output to the LLM, while preserving enough recent conversation context for useful follow-up turns and enough observability to debug agent behavior.

## Background

Logfire shows some `agent run` spans with multi-million input-token counts. The trace data indicates the issue is not a single unusually large user prompt. It is cumulative message history growth:

- `handle_chat_input` passes `app_state.pydantic_messages` into every Pydantic AI run as `message_history`.
- After each run, `handle_chat_input` appends `response.messages`, which come from `agent_run.result.new_messages()`.
- `new_messages()` includes the current run's user prompt, assistant responses, tool calls, and tool-return messages.
- The current cap, `MAX_PYDANTIC_MESSAGES = 50`, is message-count based. It does not account for token size.
- Tool-return messages can be very large. `semble_search` returns raw stdout, and `execute_python` returns full stdout/stderr JSON.
- Logfire instrumentation is configured with default Pydantic AI content capture, so `pydantic_ai.all_messages` exposes the same large message history that is being resent.

The result is multiplicative cost: a large tool result from one turn becomes part of the next turn's prompt, and remains there until enough later messages evict it by count.

## Requirements

1. Bound prompt history by approximate token count before every model request.
2. Bound retained history by approximate token count after every model response.
3. Redact or summarize oversized tool-return content before storing it in `app_state.pydantic_messages`.
4. Cap untrusted tool output at the skill boundary for high-risk tools.
5. Preserve valid Pydantic AI message ordering and tool-call/tool-return consistency.
6. Keep the latest user and assistant text turns whenever possible.
7. Keep Logfire useful, but avoid uploading full prompt/tool payloads by default.
8. Add tests that fail under the current message-count-only behavior.

## Non-Goals

- Implement semantic conversation summarization with an LLM.
- Persist full raw tool outputs in chat history.
- Change the blackboard event store schema.
- Remove Pydantic AI instrumentation entirely.
- Disable auto-invokable tools as the main mitigation.

## Proposed Behavior

### 1. Add Runtime Limits

Extend `RuntimeConfig` with explicit token and character limits:

```python
@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    database_path: Path
    default_container_image: str
    max_retries: int = 3
    max_tokens: int = 10_000
    chat_history_max_tokens: int = 24_000
    chat_history_recent_turns: int = 6
    tool_result_max_chars: int = 12_000
```

Add optional config keys under `runtime` in `harness.yaml`:

```yaml
runtime:
  database_path: harness_poc/blackboard.db
  default_container_image: python:3.12-slim
  chat_history_max_tokens: 24000
  chat_history_recent_turns: 6
  tool_result_max_chars: 12000
```

Defaults must be conservative enough to prevent accidental million-token prompts, but large enough that normal REPL follow-up remains usable.

### 2. Introduce Message History Utilities

Create `harness_poc/core/message_history.py`.

Responsibilities:

- Estimate token count for Pydantic AI `ModelMessage` objects.
- Truncate oversized tool-return content.
- Prune oldest history until the estimated token budget is met.
- Preserve valid request/response ordering.

Suggested public functions:

```python
def sanitize_new_messages(
    messages: list[ModelMessage],
    *,
    tool_result_max_chars: int,
) -> list[ModelMessage]:
    ...


def prune_message_history(
    messages: list[ModelMessage],
    *,
    max_tokens: int,
    recent_turns: int,
) -> list[ModelMessage]:
    ...


def estimate_message_tokens(messages: list[ModelMessage]) -> int:
    ...
```

Token counting can be approximate. Prefer the existing `tiktoken`-based pattern in `goal_runner.count_tokens` if available, but avoid making exact provider-specific tokenization a hard requirement.

### 3. Redact Tool Results Before Retention

When retaining Pydantic AI messages, replace very large tool-return content with a bounded placeholder:

```text
[tool result truncated: original_chars=482931 retained_chars=12000]
<first 12000 chars>
```

Apply this only to history storage. The model should still receive the full tool result inside the current run that produced it, because the agent needs the result to answer the current user request.

The truncation should cover:

- `ToolReturnPart.content` strings.
- JSON-like or structured content that serializes to a large string.
- Retry/error prompt content if it can become model-visible history.

Do not truncate normal user prompts or final assistant messages in this first implementation unless the full history cannot otherwise fit the budget.

### 4. Prune Before Sending and After Appending

Update `handle_chat_input`:

```python
history = prune_message_history(
    app_state.pydantic_messages,
    max_tokens=app_state.config.runtime.chat_history_max_tokens,
    recent_turns=app_state.config.runtime.chat_history_recent_turns,
)

response = app_state.pydantic_runtime.stream_text(
    user_input,
    message_history=history,
    ...
)

if response.messages:
    app_state.pydantic_messages.extend(
        sanitize_new_messages(
            response.messages,
            tool_result_max_chars=app_state.config.runtime.tool_result_max_chars,
        )
    )
    app_state.pydantic_messages = prune_message_history(
        app_state.pydantic_messages,
        max_tokens=app_state.config.runtime.chat_history_max_tokens,
        recent_turns=app_state.config.runtime.chat_history_recent_turns,
    )
```

The existing `MAX_PYDANTIC_MESSAGES` guard can be removed or retained as a secondary hard cap, but it must no longer be the primary safety mechanism.

### 5. Cap High-Risk Tool Outputs

Update `skills/semble_search/skill.py`:

- Change implementation default `DEFAULT_TOP_K` to match the schema default of `5`, or update schema/tests intentionally if `15` is required.
- Add `MAX_OUTPUT_CHARS`, for example `40_000`.
- Truncate successful stdout before returning `SkillResult.content`.
- Preserve truncation metadata in `artifacts`.

Example suffix:

```text

[semble output truncated: original_chars=143822 retained_chars=40000]
```

Update `harness_poc/system_skills/execute_python/skill.py`:

- Add separate stdout/stderr caps, for example `20_000` chars each.
- Return capped stdout/stderr in `content`.
- Preserve original lengths and truncation booleans in `artifacts`.
- Do not include the full executed code in model-visible content unless needed. Keeping it in `artifacts["code"]` is acceptable because the Pydantic AI tool adapter returns only `SkillResult.content` to the model.

### 6. Reduce Logfire Content Capture by Default

Update `harness_poc/core/logfire_subscriber.py` so Pydantic AI instrumentation does not capture full content by default.

Target behavior:

- Keep Logfire spans, token usage, model names, tool names, durations, and errors.
- Disable prompt/tool/result payload capture unless explicitly enabled.

Proposed config:

```yaml
observability:
  logfire: true
  logfire_include_content: false
```

Proposed implementation:

```python
def configure_logfire(*, include_content: bool = False) -> None:
    logfire.configure()
    logfire.instrument_pydantic_ai(include_content=include_content)
```

If the installed Logfire API does not support `include_content` directly on `instrument_pydantic_ai`, use the supported Pydantic AI instrumentation settings path for version `1.97.0`, or document the incompatibility and leave history/tool caps as the primary protection.

## File Map

| File | Action | Purpose |
|---|---|---|
| `harness_poc/core/config.py` | Modify | Add runtime and observability config fields |
| `harness.yaml` | Modify | Add explicit defaults for history/tool/Logfire content limits |
| `harness_poc/core/message_history.py` | Add | Token estimation, tool-result sanitization, history pruning |
| `harness_poc/repl.py` | Modify | Prune before request, sanitize/prune after response |
| `skills/semble_search/skill.py` | Modify | Align `top_k` default and cap returned stdout |
| `skills/semble_search/SKILL.md` | Modify | Keep schema/defaults aligned with implementation |
| `harness_poc/system_skills/execute_python/skill.py` | Modify | Cap stdout/stderr in model-visible content |
| `harness_poc/core/logfire_subscriber.py` | Modify | Disable content capture by default where supported |
| `tests/test_message_history.py` | Add | Unit tests for pruning and sanitization |
| `tests/test_repl_chat.py` | Modify | Assert bounded history is passed to runtime |
| `tests/test_semble_search.py` | Modify | Assert default and output truncation behavior |
| `tests/test_execute_python.py` | Modify | Assert stdout/stderr caps |

## Implementation Plan

### Task 1: Add Config Knobs

- Add `chat_history_max_tokens`, `chat_history_recent_turns`, and `tool_result_max_chars` to `RuntimeConfig`.
- Add `logfire_include_content` to `ObservabilityConfig`.
- Parse these values in `HarnessConfig.load`.
- Update tests that construct `HarnessConfig` manually.

### Task 2: Build Message History Utilities

- Add `message_history.py`.
- Implement token estimation for Pydantic AI messages via safe JSON serialization.
- Implement tool-return truncation without mutating caller-owned message instances unexpectedly.
- Implement pruning that drops oldest complete message pairs first.
- Add unit tests covering:
  - No-op under budget.
  - Oversized tool result is truncated.
  - Oldest messages are pruned until under budget.
  - Latest turns are retained as long as possible.

### Task 3: Wire REPL History Control

- Prune `app_state.pydantic_messages` before passing it into `stream_text`.
- Sanitize `response.messages` before extending retained history.
- Prune again after extending.
- Replace or demote `MAX_PYDANTIC_MESSAGES`.
- Add regression tests proving a huge tool-return message does not get passed into the next runtime call.

### Task 4: Cap Tool Outputs

- Add output caps to `semble_search`.
- Align `DEFAULT_TOP_K` with `SKILL.md` and tests.
- Add output caps to `execute_python`.
- Ensure tool outputs still clearly report truncation and original length.

### Task 5: Harden Logfire Defaults

- Extend observability config with `logfire_include_content`.
- Pass that value into Pydantic AI instrumentation where supported.
- Add a focused unit test with monkeypatching to verify the configured argument/path is used.

## Acceptance Criteria

- A single 500k-character `semble_search` result is not retained in full in `app_state.pydantic_messages`.
- The next chat turn after an oversized tool result receives a bounded `message_history`.
- `estimate_message_tokens(app_state.pydantic_messages)` remains below `runtime.chat_history_max_tokens` after chat turns complete, except when one latest user/assistant exchange alone exceeds the budget.
- `semble_search` returns at most `MAX_OUTPUT_CHARS` plus a short truncation notice in model-visible content.
- `execute_python` returns capped stdout/stderr in model-visible content.
- Logfire no longer stores full `pydantic_ai.all_messages` content by default when the installed instrumentation API supports content disabling.
- Existing chat, runtime, skill, and config tests pass.

## Test Plan

Run focused tests:

```bash
uv run pytest tests/test_message_history.py tests/test_repl_chat.py tests/test_semble_search.py tests/test_execute_python.py
```

Run static checks:

```bash
uv run ruff check .
uv run ty check
```

Run full test suite:

```bash
uv run pytest
```

Manual validation:

1. Start the REPL with Logfire enabled.
2. Ask for a code search that causes `semble_search` to return many results.
3. Ask a short follow-up question.
4. Confirm in Logfire that the follow-up request input tokens are bounded and do not include the full prior tool output.
5. Confirm tool spans still show tool name, duration, status, and token usage.

## Open Questions

- Should raw full tool outputs be persisted somewhere outside model history for debugging, or should they be discarded after the current run?
- Should the budget be model-specific, derived from the configured model context window, or kept as an explicit config value?
- Should large assistant final answers also be summarized/truncated for future turns, or is tool-return truncation sufficient for the current problem?
- Should `/state` or another command expose current retained history token estimates for debugging?
