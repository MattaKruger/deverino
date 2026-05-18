# Plan: Auto-Invokable Skills

**Date:** 2026-05-19
**Status:** draft

## Problem

The PydanticAI agent in the REPL chat (`handle_chat_input`) has `enable_tools=False`
(app_factory.py:96). Skills can only be invoked manually via `/skill <name> <args>`.
The LLM never sees available tools and can't auto-invoke them.

The user wants `semble_search` (and other safe skills) to be auto-invokable when
the LLM detects intent to search the codebase.

## Current Architecture

```
app_factory.py:96  →  build_runtime(enable_tools=False)
                           ↓
pydantic_runtime.py:build_primary_agent()
    tools=build_skill_tools(skill_runner) if enable_tools else []   ← always empty
                           ↓
pydantic_runtime.py:build_skill_tools()
    for each discovered skill → Tool.from_schema(...)                ← never runs
```

`SkillRunner.discover_skills()` scans `system_skills/` and `skills/` for `SKILL.md`
files, parses YAML frontmatter, and returns OpenAI-style tool schemas.

## Design

### 1. Add `auto_invokable` flag to SKILL.md frontmatter

```yaml
---
name: semble_search
description: ...
version: "1.0"
auto_invokable: true          # ← NEW: LLM can call this without user prompting
parameters: ...
---
```

Default: `false` (safe by default — no existing skill changes behavior).

### 2. Pass `auto_invokable` through the discovery pipeline

`SkillRunner.parse_skill_document()` already parses frontmatter. Add
`auto_invokable` to `SkillMetadata` and `SkillDocument` TypedDicts.

`SkillRunner.discover_skills()` already returns `{"type": "function", "function": {...}}`.
Add `auto_invokable: bool` alongside the function metadata, or keep it as a separate
lookup.

Simplest approach: add it to the function dict:

```python
{
    "type": "function",
    "function": {
        "name": skill_name,
        "description": ...,
        "parameters": ...,
        "auto_invokable": auto_invokable,  # NEW
    },
}
```

### 3. Filter tools in `build_skill_tools()`

```python
def build_skill_tools(skill_runner: SkillRunner) -> list[Tool[AgentDeps]]:
    tools = []
    for discovered in skill_runner.discover_skills():
        function = discovered.get("function", {})
        auto = function.get("auto_invokable", False)
        if not auto:
            continue  # skip non-auto-invokable skills
        # ... existing tool creation logic
    return tools
```

### 4. Enable tools in `build_app_state()`

Change `enable_tools=False` → `enable_tools=True` in app_factory.py:96.

Only auto-invokable skills will be registered (due to the filter in step 3).
Manual `/skill <name>` still works for ALL skills (it goes through
`SkillRunner.execute_skill()` directly, not through the agent tool system).

### 5. Update SOUL.md

Remove the `## Code Search` section that instructs the LLM to run `semble search`
as a shell command. Replace with a general tools section:

```markdown
## Available Tools

You have access to tools that can search the codebase, query the web, and more.
Use them when the user's request benefits from external information or codebase
context.

- **semble_search**: Search the codebase by describing what code does. Use this
  instead of grep or manual file inspection.
- Additional tools are described in their schemas.
```

### 6. Mark safe skills as auto-invokable

| Skill | Auto-invokable? | Reason |
|---|---|---|
| `semble_search` | ✅ yes | Read-only, local, no API cost |
| `web_search` | ✅ yes | Read-only, external API |
| `read_memory` | ✅ yes | Read-only, local DB |
| `summarize_memory` | ✅ yes | Read-only, local |
| `review_work` | ✅ yes | Read-only, local |
| `consolidate_state` | ❌ no | Mutates project state |
| `delegate_task` | ❌ no | Spawns subagents (cost, complexity) |
| `container_exec` | ❌ no | Executes arbitrary shell commands |
| `container_spawn` | ❌ no | Creates containers |
| `container_destroy` | ❌ no | Destroys containers |
| `evaluate_goal` | ❌ no | Goal loop only |
| `spec_writer` | ❌ no | Interactive, user-facing |
| `reflect_on_result` | ❌ no | Assessment tool |

### 7. Testing

- Unit test: `build_skill_tools()` only returns tools with `auto_invokable: true`
- Integration test: REPL chat with `semble_search` auto-invoked by LLM
- Verify manual `/skill delegate_task` still works (not auto-invokable, but
  manually executable)

## Files Changed

| File | Change |
|---|---|
| `skills/semble_search/SKILL.md` | Add `auto_invokable: true` |
| `skills/web_search/SKILL.md` | Add `auto_invokable: true` |
| `harness_poc/system_skills/read_memory/SKILL.md` | Add `auto_invokable: true` |
| `skills/summarize_memory/SKILL.md` | Add `auto_invokable: true` |
| `skills/review_work/SKILL.md` | Add `auto_invokable: true` |
| `harness_poc/core/skill_runner.py` | Parse `auto_invokable` from frontmatter, include in output |
| `harness_poc/core/pydantic_runtime.py` | Filter by `auto_invokable` in `build_skill_tools()` |
| `harness_poc/app_factory.py` | `enable_tools=False` → `enable_tools=True` |
| `harness_poc/system_prompts/SOUL.md` | Replace `semble` CLI instructions with tool guidance |
| `tests/test_skill_runner.py` | Test auto_invokable parsing and filtering |

## Risks

- **Token cost:** Every turn carries tool schemas in the system prompt. With 5
  auto-invokable skills schemas, this is ~200-400 extra tokens per request.
  Mitigated by DeepSeek's context caching (repeated prefix is free).
- **LLM over-invocation:** The LLM might call `web_search` or `semble_search`
  unnecessarily. Mitigated by clear tool descriptions and the system prompt
  guidance.
- **API cost for web_search:** If auto-invokable, the LLM could trigger LangSearch
  API calls without the user explicitly asking. Low risk — web_search is a
  free-tier API, and the LLM only calls it when it thinks it needs web results.
