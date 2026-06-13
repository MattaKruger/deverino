---
title: "Sub-agent spawn hardening — bounds, truncation, error safety"
date: 2026-06-13
status: draft
kind: spec
---
# Sub-agent spawn hardening — bounds, truncation, error safety

## Problem

`/spawn` sub-agents run via `_HarnessSpawner.spawn()` with no usage limits, no
tool result caps, and no binary-data guard. This causes:

1. **Runaway context growth** — tool results accumulate in the conversation
   with no size cap, growing the context until pydantic_ai internal buffers
   fail (UTF-8 decode at ~14MB observed).
2. **Unbounded tool calls** — no `tool_calls_limit`, the agent can loop
   indefinitely on tool calls until an external failure stops it.
3. **No token budget** — no `total_tokens_limit`, spends provider credits
   with no guardrail.
4. **Fragile error messages** — `str(exc)` on a `UnicodeDecodeError` with
   a 14MB position produces a bloated error string, which then gets embedded
   in the blackboard payload and printed to the TUI.

## Fix (implemented)

Four changes to `_HarnessSpawner.spawn()` (wiring.py:318-454):

### 1. Usage limits + model response cap

```python
result = agent.run_sync(
    prompt,
    model_settings=ModelSettings(max_tokens=8192),
    usage_limits=UsageLimits(
        request_limit=30,
        tool_calls_limit=20,
        total_tokens_limit=200_000,
        output_tokens_limit=8192,
    ),
)
```

`max_tokens=8192` caps individual model responses. `output_tokens_limit=8192` is the
hard enforcement. `total_tokens_limit=200_000` is generous enough for non-trivial
multi-tool tasks while preventing the 14MB+ context bloat.

### 2. Graceful UsageLimitExceeded handling

Catches `UsageLimitExceeded` separately with actionable advice:

```
"Token budget exceeded. Break this task into smaller pieces, "
"or narrow the objective to require fewer tool calls."
```

### 3. Error message truncation

`_format_exception(exc)` caps at 500 chars — prevents 14MB error strings:

```python
def _format_exception(exc: BaseException) -> str:
    msg = str(exc)
    if len(msg) > max_error_length:
        msg = msg[:max_error_length] + "..."
    return f"{type(exc).__name__}: {msg}"
```

### 4. Safe output text conversion
`_safe_output_text(result.output)` — caps at 100K chars, JSON-serializes non-str types.

## Verification

| File | Change |
|---|---|
| `harness_poc/v2/wiring.py` | Add `_format_exception()`, `_safe_output_text()` helpers. Add `UsageLimits` to `agent.run_sync()`. Guard `output_text` with `_safe_output_text`. Truncate error strings. |
| `tests/pressure/test_subagent_system.py` | Verify the spawner spy still works (no behavior change for the mock path). |

## Requirements

### R1: Sub-agent has usage limits
- `request_limit=30` — max 30 model requests
- `tool_calls_limit=20` — max 20 successful tool calls
- `total_tokens_limit=100_000` — max 100K tokens total
- Agent stops before context grows to 14MB

### R2: Error messages are bounded
- UnicodeDecodeError at position 14M → displayed as `UnicodeDecodeError: 'utf-8'... (truncated)`
- No 14MB error string in the blackboard or TUI output

### R3: Tool output is JSON-safe
- `result.output` that isn't a string → JSON-serialized or repr'd, capped at 500 chars
- No bytes objects, no non-serializable types in `raw_output`

### R4: Existing spawn behavior preserved
- `SpawnerSpy` in pressure tests unaffected
- `/spawn` with valid personas still works
- Foreground/background modes unchanged

## Non-Goals
- Per-tool return value truncation (requires tool-level changes, not spawner-level)
- Adding token tracking to spawn results
- Circuit breaker integration (no access to `AgentDeps` in spawner context)

## Verification

```bash
uv run pytest tests/pressure/test_subagent_system.py -v
```
