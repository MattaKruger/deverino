# Phase B — Agent-Inspectable ACDL Specification

**Created:** 2026-05-23
**Status:** planned
**Depends on:** Phase A complete (commits `ceb52c3`, `9ed5422`, `fe6821a`)

---

## 1. Why This Exists

The Python ACDL parser (`harness_poc/core/acdl/`) currently parses `.acdl` files
into a typed AST and validates syntax. But the AST has no query API — the only
way to extract information is by iterating `ast.blocks` and doing manual
`isinstance` checks. The CLI `inspect` command does this internally, but the
code isn't reusable.

**The goal:** make the AST programmatically queryable so the Deverino agent can
load its own specification at runtime and reason about it. The agent should be
able to answer questions like:

- "What fragments does `DeverinoChatLoop` compose?"
- "What namespace variables does `ConversationTurn[@t]` reference?"
- "List all StrFrag definitions in the file."

This closes the loop on why we built the parser in the first place.

---

## 2. Current State — What You're Working With

### File map

| File | Purpose | Key exports / classes |
|------|---------|----------------------|
| `harness_poc/core/acdl/__init__.py` | Public API | `parse()`, `validate()`, `ACDLFile`, `ParseError`, `Parser` |
| `harness_poc/core/acdl/ast.py` | 15 dataclass AST nodes | `ACDLFile`, `StrFragDef`, `RoleFragDef`, `PromptDef`, `NamespaceDef`, `RoleMessage`, `ContextVar`, `TemplateCall`, `StringLiteral`, `ConditionalBlock`, `LoopBlock`, `SwitchBlock`, `FragInvocation`, `NameDef`, `CommentBlock` |
| `harness_poc/core/acdl/parser.py` | Tokenizer + recursive-descent parser | `Parser`, `ParseError`, `Tokenizer` |
| `harness_poc/core/acdl/cli.py` | Typer CLI (`acdl validate`, `acdl inspect`) | `acdl_app` |
| `tests/test_acdl_parser.py` | 16 pytest tests + CI guard | — |
| `skills/acdl-syntax/SKILL.md` | Knowledge skill (quickstart reference) | — |
| `harness_poc/system_tools/__init__.py` | Tool registry | `register()`, `get_registry()` |
| `harness_poc/system_tools/read_memory.py` | Example tool (reference pattern) | `read_memory(ctx, memory_key)` |

### What the AST looks like

```python
ast = ACDLFile(blocks=[
    StrFragDef(name="SoulCharter", params=[], body=[ContextVar(...)]),
    RoleFragDef(name="ConversationTurn", params=["@t"], body=[ConditionalBlock(...), ...]),
    PromptDef(name="DeverinoChatLoop", indices=[TimeIndex(...)], body=[RoleMessage(...), ...]),
    NamespaceDef(name="env", bindings=[NamespaceBinding(name="user_input", type_expr="string"), ...]),
    CommentBlock(text="..."),
    ...
])
```

All nodes are frozen dataclasses with `slots=True`. Union types are defined with
the `type` statement (Python 3.14).

### Tool registration pattern

Tools are registered in `harness_poc/system_tools/` using:

```python
from harness_poc.system_tools import register as _register

def my_tool(ctx: ToolContext, ...) -> SkillResult:
    ...

_register(
    name="my_tool",
    description="...",
    parameters={"type": "object", "properties": {...}},
    handler=my_tool,
)
```

The `ToolContext` provides `session_id`, `database` (BlackboardDatabase), and
other runtime context. Tools return `SkillResult(status=..., content=...)`.

---

## 3. Implementation Steps

### B1 — AST Query API

**File:** `harness_poc/core/acdl/ast.py`
**Lines:** ~60 added to `ACDLFile` class

Add convenience query methods to `ACDLFile`. These replace the manual
`isinstance` traversal that the CLI currently does inline.

```python
@dataclass(frozen=True, slots=True)
class ACDLFile:
    blocks: list[Block]

    # -- query API --

    def str_frags(self) -> list[StrFragDef]:
        """All StrFrag definitions in file order."""
        return [b for b in self.blocks if isinstance(b, StrFragDef)]

    def role_frags(self) -> list[RoleFragDef]:
        """All RoleFrag definitions in file order."""
        return [b for b in self.blocks if isinstance(b, RoleFragDef)]

    def fragments(self) -> list[StrFragDef | RoleFragDef]:
        """All fragment definitions (StrFrag + RoleFrag) in file order."""
        return [b for b in self.blocks if isinstance(b, (StrFragDef, RoleFragDef))]

    def fragment_named(self, name: str) -> StrFragDef | RoleFragDef | None:
        """Find a fragment by name. Returns None if not found."""
        for f in self.fragments():
            if f.name == name:
                return f
        return None

    def prompts(self) -> list[PromptDef]:
        """All prompt/chart definitions in file order."""
        return [b for b in self.blocks if isinstance(b, PromptDef)]

    def prompt_named(self, name: str) -> PromptDef | None:
        """Find a prompt by name. Returns None if not found."""
        for p in self.prompts():
            if p.name == name:
                return p
        return None

    def namespaces(self) -> list[NamespaceDef]:
        """All Namespace blocks in file order."""
        return [b for b in self.blocks if isinstance(b, NamespaceDef)]

    def namespace_named(self, name: str) -> NamespaceDef | None:
        """Find a namespace by name. Returns None if not found."""
        for ns in self.namespaces():
            if ns.name == name:
                return ns
        return None
```

**Also add a body-traversal helper on `PromptDef`:**

```python
@dataclass(frozen=True, slots=True)
class PromptDef:
    name: str
    indices: list[Expression] = field(default_factory=list)
    body: list[PromptBodyItem] = field(default_factory=list)

    def role_messages(self) -> list[RoleMessage]:
        """All role messages in this prompt body (shallow, not recursive)."""
        return [item for item in self.body if isinstance(item, RoleMessage)]

    def frag_invocations(self) -> list[FragInvocation]:
        """All Frag invocations in this prompt body (shallow, not recursive)."""
        return [item for item in self.body if isinstance(item, FragInvocation)]
```

**After B1, refactor `cli.py`** to use the new query methods instead of manual
`isinstance` loops. This proves the API is usable.

---

### B2 — JSON Serialization

**File:** `harness_poc/core/acdl/ast.py` (add `to_dict()` function)
**Lines:** ~50

Add a recursive serializer that converts the AST to plain dicts/lists/strings.
This is the bridge between the typed AST and the agent's text-based interface.

```python
def to_dict(node: object) -> object:
    """Serialize an AST node to plain Python dicts/lists/primitives.

    Returns a JSON-serializable structure suitable for tool output,
    blackboard storage, or comparison with the JS renderer AST.
    """
    if isinstance(node, (str, int, float, bool)) or node is None:
        return node

    if isinstance(node, list):
        return [to_dict(item) for item in node]

    if isinstance(node, tuple):
        return [to_dict(item) for item in node]

    if hasattr(node, "__dataclass_fields__"):
        result: dict[str, object] = {"_type": type(node).__name__}
        for field_name in node.__dataclass_fields__:
            value = getattr(node, field_name)
            # Skip empty defaults to keep output compact
            if value is None or value == [] or value == {}:
                continue
            result[field_name] = to_dict(value)
        return result

    # Fallback: Token, other objects
    return str(node)
```

**Design notes:**
- Uses `_type` key to identify node types (e.g., `"StrFragDef"`, `"PromptDef"`).
  This mirrors how the JS renderer's AST nodes have a `kind` field.
- Skips empty defaults (`None`, `[]`, `{}`) to keep output compact — an agent's
  context window is large (200k) but not infinite.
- Lists and tuples both serialize to JSON arrays.
- Tokens (opaque expression carriers) serialize to their string value via
  `str()`.

**Expose in `__init__.py`:**

```python
__all__ = ["ACDLFile", "ParseError", "Parser", "parse", "to_dict", "validate"]
```

**Test expectation:** `json.dumps(to_dict(ast))` produces valid JSON. Round-trip
is not required (this is one-way: AST → JSON).

---

### B3 — Tool Registration

**New file:** `harness_poc/system_tools/acdl_tools.py`
**Lines:** ~40

Register `acdl_inspect` as an LLM-callable tool. The tool loads an `.acdl`
file, parses it, and returns a structural summary as JSON.

```python
"""acdl_inspect — inspect an ACDL specification file.

Returns a structural summary (fragments, prompts, namespaces) as JSON.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from harness_poc.core.acdl import parse, to_dict
from harness_poc.core.skills import SkillResult

if TYPE_CHECKING:
    from harness_poc.core.tools import ToolContext


def acdl_inspect(
    ctx: ToolContext,
    file_path: str = "",
) -> SkillResult:
    """Parse an .acdl file and return its structural summary."""
    from pathlib import Path

    path = Path(file_path)
    if not path.exists():
        return SkillResult(
            status="failed",
            content=f"File not found: {file_path}",
        )
    if path.suffix != ".acdl":
        return SkillResult(
            status="failed",
            content=f"Not an .acdl file: {file_path}",
        )

    try:
        source = path.read_text()
        ast = parse(source, filename=str(path))
        summary = {
            "file": str(path),
            "block_count": len(ast.blocks),
            "str_frags": [f.name for f in ast.str_frags()],
            "role_frags": [f.name for f in ast.role_frags()],
            "prompts": [p.name for p in ast.prompts()],
            "namespaces": [ns.name for ns in ast.namespaces()],
        }
        return SkillResult(
            status="success",
            content=json.dumps(summary, indent=2),
            artifacts={"acdl_summary": summary, "acdl_ast": to_dict(ast)},
        )
    except Exception as e:
        return SkillResult(
            status="failed",
            content=f"Failed to parse {file_path}: {e}",
        )


# ── Register ──────────────────────────────────────────────────────────

from harness_poc.system_tools import register as _register  # noqa: E402

_register(
    name="acdl_inspect",
    description=(
        "Parse an .acdl (Agent Context Definition Language) specification file "
        "and return its structural summary: fragment definitions, prompt "
        "definitions, and namespace blocks. Use this to inspect the harness's "
        "own architecture specification."
    ),
    parameters={
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Path to the .acdl file to inspect (e.g., 'deverino_react.acdl').",
            },
        },
        "required": ["file_path"],
    },
    handler=acdl_inspect,
)
```

**Note on imports:** The `from harness_poc.system_tools import register as
_register` must be at module level (after the function definition) to match the
existing tool pattern. This triggers registration at import time — the
`system_tools/__init__.py` imports all tool modules to populate the registry.

**If you need the full AST in tool output** (not just the summary), the
`artifacts` dict contains `acdl_ast` as the full `to_dict()` output. The agent
can request this if it needs deeper inspection.

---

### B4 — Expression Parsing (Optional)

**File:** `harness_poc/core/acdl/parser.py`
**Lines:** ~150

Currently, conditions (`If env.x != none`), iterables (`range(1, @T)`), and
switch expressions are stored as raw `list[Token]`. This makes them opaque to
queries. B4 parses them into typed expression ASTs.

**What to parse:**

- **Comparisons:** `expr != none`, `@T > 1`, `expr == value`
- **Path access:** `event.type` → `ContextVar(namespace="event", path=["type"])`
- **Function calls:** `range(a, b)`, `max(a, b)` → `TemplateCall`
- **Arithmetic:** `@T - 6`, `1 + 2`

**New AST nodes (add to `ast.py`):**

```python
@dataclass(frozen=True, slots=True)
class Comparison:
    """A comparison expression: left OP right"""
    left: Expression
    operator: str  # "!=", "==", ">", "<", ">=", "<="
    right: Expression


@dataclass(frozen=True, slots=True)
class PathAccess:
    """A dotted path access: event.type"""
    base: Expression
    path: list[str]
```

**Update `Expression` type to include these.**

**Parser changes:**
- Replace `_collect_until_brace()` in conditions with `_parse_expression()`
- Handle `!=`, `==`, `>`, `<` as comparison operators
- Handle `.` as path access

**Only do B4 if the agent actually needs to query control flow semantics.** The
raw-token approach is sufficient for "list all fragments/prompts/namespaces"
which is the primary use case.

---

## 4. Acceptance Criteria

After each step, verify:

### B1
```bash
uv run python3 -c "
from harness_poc.core.acdl import parse
from pathlib import Path
ast = parse(Path('deverino_react.acdl').read_text(), filename='t')
assert len(ast.str_frags()) == 9
assert len(ast.role_frags()) == 3
assert len(ast.prompts()) == 2
assert ast.fragment_named('SoulCharter') is not None
assert ast.prompt_named('DeverinoChatLoop') is not None
assert ast.fragment_named('Nonexistent') is None
print('B1 OK')
"
```

### B2
```bash
uv run python3 -c "
from harness_poc.core.acdl import parse, to_dict
import json
ast = parse(open('deverino_react.acdl').read(), filename='t')
data = to_dict(ast)
assert isinstance(data, dict)
assert data['_type'] == 'ACDLFile'
assert len(data['blocks']) == 52
print(json.dumps(data, indent=2)[:200])
print('B2 OK')
"
```

### B3
```bash
uv run python3 -c "
from harness_poc.system_tools.acdl_tools import acdl_inspect
# Unit test: call handler directly
class FakeCtx:
    session_id = 'test'
    database = None
result = acdl_inspect(FakeCtx(), 'deverino_react.acdl')
assert result.status == 'success'
print(result.content[:200])
print('B3 OK')
"
```

### All together
```bash
uv run pytest tests/test_acdl_parser.py -v  # all pass
uv run pytest tests/ -x --tb=short           # full suite, no regressions
uv run ruff check harness_poc/core/acdl/     # clean
uv run ty check harness_poc/core/acdl/       # clean
```

---

## 5. Execution Order

```
B1 (query API) → B2 (JSON) → B3 (tool) → [B4 (expressions, optional)]
```

B1 is the foundation. B2 makes the AST communicable. B3 closes the loop by
making it callable by the agent. B4 is depth for when the agent needs to
understand control flow semantics.

**Suggested commit strategy:** One commit per step. Each is independently
testable and doesn't break existing functionality.

---

## 6. Handoff Notes

- The `ACDLFile` dataclass is in `harness_poc/core/acdl/ast.py` starting at
  line ~34. Add query methods directly to the class body.
- The `to_dict()` function should go at the bottom of `ast.py` (after all
  class definitions).
- The CLI's `_index_to_str()` helper in `cli.py` is a one-off for display.
  Don't reuse it for serialization — use `to_dict()` instead.
- After B1, refactor `cli.py`'s `inspect_acdl()` to use the query methods.
  This is both a cleanup and a proof that the API works.
- Tool files in `system_tools/` are auto-imported by `__init__.py`. Just
  creating the file registers the tool — no manual import needed elsewhere.
- The tool handler receives `ToolContext` as first argument (even if unused).
  The pattern is: `def handler(ctx: ToolContext, **params) -> SkillResult`.
- All 550 existing tests must continue to pass at each step.
