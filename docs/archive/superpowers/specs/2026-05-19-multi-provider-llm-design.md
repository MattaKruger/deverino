# Multi-Provider LLM Support — Design Spec

**Date:** 2026-05-19
**Status:** Approved

## Overview

Replace the DeepSeek-only `LLMClient` with a clean provider abstraction backed by PydanticAI. The provider and model are declared in `harness.yaml`; credentials come from env vars. Supports any OpenAI-compatible endpoint and Anthropic as a first-class case.

## Goals

- Configure provider + model in `harness.yaml` (one place per repo)
- Credentials from env vars only — never in config files
- Support: `deepseek`, `openai` (and any OpenAI-compatible base URL), `anthropic`
- Remove `LLMClient` and `DeepSeekSettings` — unify on PydanticAI
- No API key → fall back to `TestModel` (same mock behaviour as today)

## Non-Goals

- Dynamic provider switching at runtime
- Per-skill provider overrides
- Streaming token display differences per provider

## Configuration

### `harness.yaml`

```yaml
llm:
  provider: deepseek          # deepseek | openai | anthropic
  model: deepseek-v4-flash
  base_url: ~                 # optional — for custom openai-compatible endpoints only
```

### Credentials (env vars)

| Provider | Env var |
|---|---|
| `deepseek` | `DEEPSEEK_API_KEY` |
| `openai` | `OPENAI_API_KEY` |
| `anthropic` | `ANTHROPIC_API_KEY` |

### Example provider configs

**OpenAI:**
```yaml
llm:
  provider: openai
  model: gpt-4o
```

**Anthropic:**
```yaml
llm:
  provider: anthropic
  model: claude-sonnet-4-6
```

**Local Ollama (OpenAI-compatible):**
```yaml
llm:
  provider: openai
  model: llama3
  base_url: http://localhost:11434/v1
```

## Architecture

### New: `LLMConfig` in `config.py`

```python
@dataclass(frozen=True, slots=True)
class LLMConfig:
    provider: str        # "deepseek" | "openai" | "anthropic"
    model: str
    base_url: str | None  # None unless overriding endpoint
```

Added to `HarnessConfig`:

```python
@dataclass(frozen=True, slots=True)
class HarnessConfig:
    ...
    llm: LLMConfig
```

Parsed in `HarnessConfig.load()` from the `llm:` section with defaults:
- `provider`: `"deepseek"`
- `model`: `"deepseek-v4-flash"`
- `base_url`: `None`

### Updated: `build_model()` in `pydantic_runtime.py`

```python
def build_model(config: LLMConfig | None = None) -> Model:
    if config is None:
        return TestModel(call_tools=[])

    if config.provider == "anthropic":
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            return TestModel(call_tools=[])
        return AnthropicModel(config.model, provider=AnthropicProvider(api_key=api_key))

    if config.provider == "deepseek":
        api_key = os.environ.get("DEEPSEEK_API_KEY")
        if not api_key:
            return TestModel(call_tools=[])
        return OpenAIChatModel(config.model, provider=DeepSeekProvider(api_key=api_key))

    # "openai" or any openai-compatible
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return TestModel(call_tools=[])
    provider_kwargs: dict[str, Any] = {"api_key": api_key}
    if config.base_url:
        provider_kwargs["base_url"] = config.base_url
    return OpenAIChatModel(config.model, provider=OpenAIProvider(**provider_kwargs))
```

`build_runtime()` and `build_primary_agent()` receive `config.llm` from `AppState` instead of reading `DeepSeekSettings`.

`GoalRunner._decide_next_action()` already accepts an optional `decision_model` override — no change needed there.

### Removed: `LLMClient` and `DeepSeekSettings`

`llm_client.py` retains only the shared TypedDicts used across the codebase:

| Kept | Removed |
|---|---|
| `Message` | `LLMClient` |
| `Usage` | `DeepSeekSettings` |
| `ToolCall` | `_deepseek_chat`, `_deepseek_stream_chat` |
| `LLMResponse` | `_build_chat_request`, `_extract_usage` |
| | `find_dotenv`, `_chunk_text`, `_safe_int` |

`AppState.llm_client: LLMClient` field is removed. `build_app_state()` no longer constructs `LLMClient`.

### Updated: REPL prompt bar

Reads from `app_state.config.llm` instead of `app_state.llm_client`:

```
[deepseek · deepseek-v4-flash]
[anthropic · claude-sonnet-4-6]
[openai · gpt-4o]
[mock]
```

The DeepSeek-specific `reason:high` annotation is removed — it doesn't generalise to other providers.

## File Map

| Action | File | Change |
|---|---|---|
| Modify | `harness_poc/core/config.py` | Add `LLMConfig`, add `llm: LLMConfig` to `HarnessConfig` |
| Modify | `harness.yaml` | Add `llm:` section |
| Modify | `harness_poc/core/pydantic_runtime.py` | Replace `DeepSeekSettings` dispatch with `LLMConfig` dispatch; add `AnthropicModel`/`AnthropicProvider` imports |
| Modify | `harness_poc/core/llm_client.py` | Delete `LLMClient`, `DeepSeekSettings`, and all DeepSeek-specific helpers |
| Modify | `harness_poc/app_factory.py` | Remove `llm_client` from `AppState`; pass `config.llm` to `build_runtime()` |
| Modify | `harness_poc/repl.py` | Update `_build_prompt_bar` to read from `config.llm` |
| Modify | `tests/test_*.py` | Add `llm=LLMConfig(...)` to all `_test_config()` helpers; delete `LLMClient` tests |

## Error Handling

- Missing API key → `TestModel` (mock mode), same behaviour as today
- Unknown `provider` value in `harness.yaml` → `ValueError` raised at startup in `build_model()`
- `base_url` set for `anthropic` provider → silently ignored (Anthropic does not use a custom base URL)

## Testing

- `test_pydantic_runtime.py`: replace `DeepSeekSettings`-based `build_model` tests with `LLMConfig`-based tests for all three provider paths, using env var monkeypatching
- All `_test_config()` helpers across test files: add `llm=LLMConfig(provider="deepseek", model="deepseek-v4-flash", base_url=None)`
- Delete any test that constructs `LLMClient` or `DeepSeekSettings` directly
