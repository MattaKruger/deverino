# Phase B — Agent-Inspectable ACDL Specification

**Created:** 2026-05-23
**Status:** B1–B3 complete, B4 deferred
**Depends on:** Phase A complete (commits `ceb52c3`, `9ed5422`, `fe6821a`, `f93a7b6`)

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

### B4 — Expression Parsing (Revised, May 2026)

**Status:** planned — deferred until programmatic condition queries are needed.

#### B4.1 — Why This Is Optional (Contrastive Analysis)

Three sources ground this decision:

1. **The ACDL paper** (Vespa: `docs/papers_2/2605.01920.pdf`, chunks 25, 39):
   Conditions may use comparison operators (`==`, `!=`, `<`, `>`) and logical
   connectives (`&`, `|`). Arithmetic operators (`+`, `-`, `*`, `/`, `%`) are
   permitted in index positions. But the paper does not define a formal
   expression AST — it defines syntax, not typed representation.

2. **The JS reference renderer** (`docs/acdl/acdl-renderer.js:1274`):
   `parseConditionalOutside()` and siblings collect raw `toExprToken()` arrays
   for conditions, iterables, and switch expressions. The renderer does NOT
   parse them into typed AST nodes. It uses `parseSingleTextArg()` for
   arithmetic inside text arguments (producing `arithmeticExpr`), but control
   flow expressions stay as token lists. Our Python parser's
   `_collect_until_brace()` mirrors this behavior exactly.

3. **The actual `.acdl` files** (52 + 155 + 14 blocks):
   Every control flow expression pattern is cataloged in §B4.3 below. The
   grammar is tiny — no operator nesting, no parentheses, no logical
   connectives in use.

**What the agent can already do without B4:** `to_dict()` serializes
`ConditionalBlock.if_condition` as structured token objects
(`{"_type": "Token", "type": "IDENT", "value": "env"}`). An LLM reading
JSON token sequences can reconstruct `env.user_input[@t] != none` — token
stream reading is its native operation. The `acdl_inspect` tool already
returns fragment/prompt/namespace names for structural queries.

**What B4 enables that raw tokens don't:**

- **Programmatic queries:** "find all conditions comparing against `none`"
  without string-matching token values.
- **Cross-reference validation:** "does every `ContextVar` in a condition
  reference a defined namespace?" for CI-time consistency checks.
- **Compact serialization:** typed nodes are ~40% smaller than token lists
  in JSON output (one `Comparison` node vs. 5–8 `Token` dicts).
- **Future evaluation:** if the harness ever conditionally assembles prompts
  at runtime, typed expressions are the prerequisite.

**Verdict:** B4 is developer infrastructure, not agent infrastructure. The
agent can reason about control flow from token output. Implement B4 when
programmatic condition queries or cross-reference validation are needed.

#### B4.2 — Changes From Original Plan

| Original plan | Revised | Reason |
|---|---|---|
| New node: `PathAccess` | **Dropped** | `ContextVar` already has `path: list[str]`. `event.type` is `ContextVar(namespace="event", path=["type"])` — no new node needed. |
| New node: `Comparison` | **Kept, unchanged** | — |
| No arithmetic node | **New node: `BinaryOp`** | `@T - 6` and `@T - budget.chat_history_turns` appear in actual `.acdl` files. The paper confirms `+`, `-`, `*`, `/`, `%` are part of the language. |
| No identifier node | **New node: `Identifier`** | Case values (`SkillCalled`) and the `none` literal aren't `NameRef` ($-prefixed) or `TemplateCall` (parenthesized). |
| `Comparison` vs `BinaryOp` separate? | **Yes, separate** | They occupy different grammar positions: comparisons only at condition level (If/ElseIf), arithmetic only inside function args and indices. Keeping them separate makes queries self-documenting: `isinstance(cond, Comparison)` reads better than checking `operator in ("!=", "==", ...)`. |
| ~150 lines estimate | **~80 lines** | The grammar has no operator precedence problems (see §B4.3). A two-level recursive descent suffices. |

#### B4.3 — Expression Grammar Inventory

Every expression pattern across all 3 `.acdl` files (verified 2026-05-23):

```
ATOM:    env.x, sys.x, resp.x     → ContextVar
         event.type               → ContextVar (path access via existing path field)
         @T, @t                   → TimeIndex
         range(...), max(...)     → TemplateCall
         SkillCalled, none        → Identifier  [NEW]
         1, 6, 10                 → NumberLiteral
         "string"                 → StringLiteral
         $max_iterations          → NameRef

POSTFIX: .ident                    → extends ContextVar.path (existing)
         [expr]                    → index (existing, on ContextVar/TimeIndex/NameRef)

INFIX:   != none                   → Comparison  [NEW]  (condition level only)
         @T > 1                   → Comparison  [NEW]
         @T - 6                   → BinaryOp    [NEW]  (function args only)
         @T % 25                  → BinaryOp    [NEW]  (per paper §39, not yet in our files)

NOT IN USE (deferred):  and (&), or (|), parentheses, unary -, ternary
```

The grammar has **no operator precedence problem** because:
- Comparisons (`!=`, `>`) only appear as the top-level condition after `If`
  — they never nest inside other expressions in any `.acdl` file.
- Arithmetic (`-`) only appears inside `TemplateCall` arguments — never at
  condition level.
- There are no parenthesized sub-expressions that would create ambiguity.
- Logical connectives (`&`, `|`) are in the paper's grammar but absent from
  all actual `.acdl` files. Defer until needed.

#### B4.4 — New AST Nodes

```python
@dataclass(frozen=True, slots=True)
class Comparison:
    """A comparison expression: left OP right.

    Only appears at condition level (If, ElseIf).
    """
    left: Expression
    operator: str  # "!=", "==", ">", "<", ">=", "<="
    right: Expression


@dataclass(frozen=True, slots=True)
class BinaryOp:
    """An arithmetic expression: left OP right.

    Appears inside function arguments and index expressions.
    Operators: "+", "-", "*", "/", "%"
    """
    left: Expression
    operator: str  # "+", "-", "*", "/", "%"
    right: Expression


@dataclass(frozen=True, slots=True)
class Identifier:
    """A bare identifier used as a value — not a namespace prefix, not a $var.

    Used for: Case match values (SkillCalled), the 'none' literal,
    and any other keyword-like identifier appearing in expression position.
    """
    name: str
```

**Updated Expression union:**

```python
type Expression = (
    ContextVar | TemplateCall | StringLiteral | NumberLiteral
    | NameRef | TimeIndex | Comparison | BinaryOp | Identifier
)
```

Three additions: `Comparison`, `BinaryOp`, `Identifier`.

#### B4.5 — Field Type Changes

Five fields migrate from `list[Token]` to typed expressions. These are
**backward-incompatible** — any code destructuring these fields as lists
will break. Currently no such code exists outside the test suite.

| Class | Field | Old type | New type |
|---|---|---|---|
| `ConditionalBlock` | `if_condition` | `list[Token]` | `Expression` |
| `ConditionalBlock` | `else_if_conditions` | `list[list[Token]]` | `list[Expression]` |
| `LoopBlock` | `iterable` | `list[Token]` | `Expression` |
| `SwitchBlock` | `expression` | `list[Token]` | `Expression` |
| `SwitchCase` | `match` | `list[Token]` | `Expression` |

`NameDef.value` stays `list[Token]` — its "rest of line" grammar isn't
enclosed by braces/parens and doesn't benefit from expression parsing.

#### B4.6 — Parser Changes (~80 lines)

**New method: `_parse_condition()`** — parses expression with optional infix
comparison operator. Used for If conditions, ForEach iterables, Switch
expressions, and Case matches:

```python
def _parse_condition(self) -> Expression:
    """Parse an expression with optional infix comparison operator.

    Handles: expr, expr != expr, expr > expr, expr == expr, etc.
    """
    left = self._parse_expression()
    op = self._peek.value
    if op in ("!=", "==", ">", "<", ">=", "<="):
        self._pos += 1
        right = self._parse_expression()
        return Comparison(left=left, operator=op, right=right)
    return left
```

**Modified: `_parse_expression()`** — add arithmetic and bare identifiers to
the existing atom parser:

```python
# After parsing left atom, check for arithmetic operators
left = atom_result
op = self._peek.value
if op in ("+", "-", "*", "/", "%"):
    self._pos += 1
    right = self._parse_expression()
    return BinaryOp(left=left, operator=op, right=right)
return left
```

And in the atom dispatch, add:

```python
# Bare identifier (e.g., 'none', Case values)
if tok.type == "KEYWORD" and tok.value not in _NAMESPACE_KEYWORDS:
    return Identifier(name=self._consume("KEYWORD").value)
```

**Wiring — replace raw token collection with `_parse_condition()`:**

| Location | Current | New |
|---|---|---|
| `_parse_conditional` line ~662 | `_collect_until_brace()` | `_parse_condition()` |
| `_parse_conditional` line ~676 (ElseIf) | `_collect_until_brace()` | `_parse_condition()` |
| `_parse_loop` line ~706 | `_collect_until(")")` | `_parse_condition()` |
| `_parse_switch` line ~715 | `_collect_until_brace()` | `_parse_condition()` |
| `_parse_switch` line ~727 (Case match) | `_collect_until_brace()` | `_parse_condition()` |

#### B4.7 — Explicitly Out of Scope

- **No logical operators** (`&`, `|`) — in the paper's grammar but absent from
  all `.acdl` files. Add when needed with proper precedence handling.
- **No parenthesized sub-expressions** — not present. Add when needed.
- **No unary operators** (`-x`, `!x`) — not present.
- **No operator precedence** — the grammar has no infix nesting that would
  require it. Comparisons never contain other comparisons; arithmetic only
  appears as direct children of function arguments.
- **No type-checking** — this is a parser, not a type-checker.
  `Identifier("none")` vs `none` keyword semantics is a downstream concern.
- **No expression evaluation** — the AST is for inspection, not execution.
- **No change to `NameDef.value`** — its "rest of line" grammar isn't
  expression-shaped.

#### B4.8 — Acceptance Criteria

```bash
uv run python3 -c "
from harness_poc.core.acdl import parse
from harness_poc.core.acdl.ast import Comparison, Identifier, ContextVar, BinaryOp, TemplateCall
from pathlib import Path

ast = parse(Path('deverino_react.acdl').read_text(), filename='t')

# Find ConversationTurn fragment
ct = ast.fragment_named('ConversationTurn')
assert ct is not None

# First condition: env.user_input[@t] != none
first_if = ct.body[0]
assert isinstance(first_if.if_condition, Comparison)
assert first_if.if_condition.operator == '!='
assert isinstance(first_if.if_condition.left, ContextVar)
assert first_if.if_condition.left.namespace == 'env'
assert isinstance(first_if.if_condition.right, Identifier)
assert first_if.if_condition.right.name == 'none'

# DeverinoChatLoop: ForEach(@t: range(max(1, @T - 6), @T))
loop = ast.prompt_named('DeverinoChatLoop')
foreach = [b for b in loop.body if hasattr(b, 'iterable')][0]
assert foreach.variable == '@t'
assert isinstance(foreach.iterable, TemplateCall)
assert foreach.iterable.name == 'range'
print('B4 OK')
"
```

#### B4.9 — Execution Notes

- B4 is independent of B1–B3 and can be implemented at any time.
- The field type changes are **backward-incompatible** — verify no downstream
  code destructures these fields as `list[Token]` before merging.
- The `to_dict()` serializer handles new node types automatically (they're
  frozen dataclasses).
- The JS renderer is unaffected — it parses its own AST independently.
- Estimated implementation time: ~30 minutes for parser changes, ~15 minutes
  for AST changes + test updates.

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
B1 (query API) → B2 (JSON) → B3 (tool) → [B4 (expressions, deferred)]
```

B1–B3 are complete (commits pending). B4 is deferred per §B4.1 — the agent
can reason about control flow from `to_dict()` token output. Implement when
programmatic condition queries or cross-reference validation are needed.

**Suggested commit strategy:** One commit per implemented step. Each is
independently testable and doesn't break existing functionality.

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
