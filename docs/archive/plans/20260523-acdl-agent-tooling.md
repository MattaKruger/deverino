# ACDL Agent Tooling — Teach the Agent to Inspect Its Own Architecture

**Status:** planned  
**Depends on:** Phase B (B1–B4) complete — `acdl_inspect` tool registered, expression
parsing done, `to_dict()` / query API available.

## 1. Current State

`acdl_inspect` is already discovered at runtime by `ToolRunner._ensure_discovered()`
(via `importlib.import_module("harness_poc.system_tools.acdl_tools")`). It appears
in the 20-tool registry, executes correctly, and returns structured JSON:

```json
{
  "file": "deverino_react.acdl",
  "block_count": 52,
  "str_frags": ["SoulCharter", "StateBlock", ...],
  "role_frags": ["ConversationTurn", "GoalEvaluationTurn", "EventMappedTurn"],
  "prompts": ["DeverinoChatLoop", "DeverinoGoalLoop"],
  "namespaces": ["env", "sys", "resp"]
}
```

The `acdl_ast` artifact (full `to_dict()` serialization) is also available in the
tool result's `artifacts` dict.

**What's missing:** the agent doesn't know this tool exists, when to reach for it,
or how to interpret its output. The two existing ACDL knowledge skills
(`acdl-syntax`, `deverino-react-acdl`) describe syntax and architecture but don't
mention programmatic inspection.

## 2. What We're Building

Two additions, both small:

### 2.1 Knowledge skill: `acdl-tooling`

A `type: knowledge` skill that teaches the agent about the `acdl_inspect` tool.
Structure:

```
skills/acdl-tooling/SKILL.md
```

Content outline:

- **Tool reference** — `acdl_inspect(file_path)` signature, parameters, return
  shape (status, artifacts, content)
- **When to use** — heuristics: user asks about harness structure, fragment
  inventory, prompt names, namespace bindings, "what's in this .acdl file?"
- **When NOT to use** — for syntax questions (use `acdl-syntax` skill), for
  architecture documentation (use `deverino-react-acdl` skill), for reading
  raw file content
- **Interpreting results** — what each field means, how to use block counts
  and lists to answer structural questions
- **The `acdl_ast` artifact** — full `to_dict()` output, token-efficient for
  LLM consumption (typed nodes are ~40% smaller than raw token lists), what
  to look for in it

### 2.2 Update `acdl-syntax` knowledge skill

Add a "Programmatic Inspection" section at the bottom referencing `acdl_inspect`
as the tool counterpart to the CLI `acdl inspect` command. One paragraph, linking
to `acdl-tooling` for details. This cross-references the two skills without
duplicating content.

## 3. Implementation

### Step 1 — Create `skills/acdl-tooling/SKILL.md`

~60 lines. Frontmatter: `type: knowledge`, `auto_invokable: false`.

Body sections:
1. **Tool: `acdl_inspect`** — signature, parameters, return value structure
2. **When to use this tool** — 4–5 concrete scenarios with example questions
3. **Interpreting the output** — field-by-field reference
4. **The `acdl_ast` artifact** — what `to_dict()` produces, when to drill into it
5. **Related skills** — `acdl-syntax` (syntax reference), `deverino-react-acdl`
   (architecture documentation)

No `skill.py` needed — this is a knowledge skill, not executable.

### Step 2 — Patch `skills/acdl-syntax/SKILL.md`

Add a **Programmatic Inspection** section (~8 lines) after the "Reference" section:

```markdown
### Programmatic Inspection

The `acdl_inspect` tool parses `.acdl` files and returns a structural summary
(fragments, prompts, namespaces, block count). Use it when you need to answer
questions like "what fragments are defined?" or "which namespaces does this
prompt declare?" For the full tool reference, see the `acdl-tooling` skill.
```

### Step 3 — Verify

```bash
# 1. Skill appears in catalog
uv run python3 -c "
from harness_poc.core.skills import build_skill_catalog
from pathlib import Path
catalog = build_skill_catalog([Path('skills')])
assert 'acdl-tooling' in catalog
print('OK')
"

# 2. Agent can call acdl_inspect (already works, verify again)
uv run python3 -c "
from harness_poc.core.tools.tool_runner import ToolRunner
from harness_poc.core.config import HarnessConfig
from pathlib import Path
config = HarnessConfig.load(Path('harness.yaml'))
runner = ToolRunner(config)
result = runner.execute_tool('acdl_inspect', {'file_path': 'deverino_react.acdl'})
import json
data = json.loads(result)
assert data['status'] == 'success'
assert 'SoulCharter' in data['content']
print('OK')
"

# 3. Full test suite unaffected
uv run pytest tests/ -x --tb=short
```

## 4. Acceptance Criteria

- `acdl-tooling` skill appears in the `build_skill_catalog()` output
- `acdl-syntax` skill references `acdl_inspect` tool and `acdl-tooling` skill
- `acdl_inspect` tool executes correctly (regression check)
- Full test suite passes
- Ruff clean on any touched files

## 5. Out of Scope

- **No new tools.** `acdl_inspect` already exists and is wired.
- **No `acdl_query` tool.** The B1 query API (`fragment_named()`, `prompts()`,
  etc.) is Python-only. A separate tool wrapping it could be useful for
  targeted queries (e.g., "find the body of ConversationTurn") but adds
  complexity. Defer until the agent demonstrates a concrete need.
- **No ACDL validation tool.** The CLI `acdl validate` command exists but
  has no LLM-callable tool counterpart. Defer until needed.
- **No runtime injection of ACDL-derived config.** This plan is about agent
  introspection, not harness configuration.
