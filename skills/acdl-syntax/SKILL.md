---
name: acdl-syntax
type: knowledge
description: >-
  Quickstart reference for the Agent Context Definition Language (ACDL) as used
  in Deverino harness specification files. Covers syntax, conventions, and
  gotchas. For the full grammar see paper 2605.01920 Appendix D.
version: "1.0"
---

## Quickstart

ACDL (Agent Context Definition Language) is a declarative language for specifying
LLM prompt structures, fragment compositions, and ReAct-style agent loops. Deverino
uses `.acdl` files to document and visualize its chat loop and goal loop architecture.

### File Structure

A `.acdl` file contains top-level blocks in any order:

- **Fragment definitions** (`StrFrag`, `RoleFrag`) — reusable prompt fragments
- **Prompt definitions** (`Name[@T]: { ... }`) — complete prompt/chart specifications
- **Namespace blocks** (`Namespace name := { ... }`) — typed variable declarations
- **Comments** (`// ...`) — documentation and annotations

### Comments

Only `//` line comments are valid. The `#` character is not part of ACDL.

```acdl
// This is a comment
StrFrag MyFrag: { ... }  // inline comment
```

### Fragment Definitions

**StrFrag** — a string-producing fragment whose body contains context variables,
template calls, and string literals:

```acdl
StrFrag Greeting: {
    "Hello, "
    sys.user_name
    "!"
}
```

**RoleFrag** — a role-structured fragment whose body contains role-tagged messages
(`U:`, `A:`, `S:`, `T:`) and control flow:

```acdl
RoleFrag Turn[@t]: {
    U: env.user_input[@t]
    A: resp.answer[@t]
}
```

Fragments can have parameters in brackets:

```acdl
RoleFrag Turn[@t]: { ... }
StrFrag PolicyBlock[@T, $budget]: { ... }
```

### Prompt Definitions

A prompt definition names a complete prompt structure with optional indices:

```acdl
MyChatLoop[@T]: {
    S: {
        Frag SystemBlock
        Frag ToolPolicy
    }
    U: env.user_input[@T]
}
```

### Fragment Invocation

Use `Frag Name` to include a fragment. Pass arguments with indices:

```acdl
Frag ConversationTurn[@t]
Frag GoalHeader
```

### Namespace Blocks

Declare typed variables that templates and fragments can reference:

```acdl
Namespace env := {
    user_input: string
    tool_results: string[]
    token_usage: (int, int, int)
}
```

Standard namespaces: `env`, `sys`, `resp`. Custom namespaces (e.g. `budget`) are
also supported.

### Control Flow

```acdl
If env.x != none {
    U: env.x
}

If @T > 1 {
    ForEach(@t: range(1, @T)) {
        Frag Turn[@t]
    }
}

Switch event.type {
    Case SkillCalled: { A: "called" }
    Case SkillCompleted: { U: "done" }
    Default: { U: "unknown" }
}
```

### Expressions

- **Context variables:** `sys.soul_charter`, `env.user_input[@t]`
- **Template calls:** `ACTION_RECORD(call)`, `BUDGET_LINE("- Max: ", env.max)`
- **String literals:** `"some text"`
- **Numbers:** `1`, `24000`
- **Time indices:** `@T`, `@t` (use in variable positions and expressions)
- **Name references:** `$max_iterations` (dollar-prefixed variables)

### Conventions

- Fragment names use PascalCase: `SoulCharter`, `ConversationTurn`
- Prompt names use PascalCase: `DeverinoChatLoop`, `DeverinoGoalLoop`
- Fragment definitions should live at file top level, not nested inside prompts
- Use companion files for visualization-focused variants (e.g., `_renderable.acdl`
  for Mark blocks and template placeholders)
- Non-standard annotations (`Struct`, `Event`, `Pipeline`, `Flow`, `Fact`) are
  skipped by the parser — they serve as documentation, not executable spec

### Gotchas

- Single-line role syntax (`U: expr`) only accepts context variables and template
  calls, not string literals. Use `U: { "text" }` for strings in role bodies.
- The `=` character must be in the symbol set for `:=` to tokenize correctly.
- Namespace names that are also keywords (`env`, `sys`, `resp`) work as identifiers
  in `Namespace name := { ... }` declarations.

### Reference

Full grammar: paper 2605.01920, Appendix D (ACDL specification).
Python parser: `harness_poc/core/acdl/parser.py`.
JS renderer: `docs/acdl/acdl-renderer.js`.

Validate any `.acdl` file:
```bash
uv run harness-poc acdl validate deverino_react.acdl
```

### Programmatic Inspection

The `acdl_inspect` tool parses `.acdl` files and returns a structural summary
(fragments, prompts, namespaces, block count). Use it when you need to answer
questions like "what fragments are defined?" or "which namespaces does this
prompt declare?" It is the LLM-callable counterpart to `harness-poc acdl inspect`.
For the full tool reference, see the `acdl-tooling` skill.
