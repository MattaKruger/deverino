---
name: acdl-tooling
type: knowledge
description: >-
  Teaches the agent how to use the acdl_inspect tool to programmatically
  inspect ACDL specification files. Covers when to reach for the tool,
  how to interpret its structured output, and the acdl_ast artifact.
version: "1.0"
---

## Tool: `acdl_inspect`

`acdl_inspect` is an LLM-callable tool that parses an `.acdl` file and returns a
structural summary. It is the programmatic counterpart to the CLI command
`harness-poc acdl inspect`.

### Signature

```
acdl_inspect(file_path: str) → SkillResult
```

**Parameters:**
- `file_path` (required) — path to an `.acdl` file. Works with relative paths
  from the project root (e.g., `"deverino_react.acdl"`,
  `"docs/acdl/deverino_loop_full.acdl"`).

### Return value

The tool returns a `SkillResult` with:

- `status`: `"success"` or `"failed"`
- `content`: JSON string with the structural summary
- `artifacts`: dict with `acdl_summary` (same as content, as a dict) and
  `acdl_ast` (full `to_dict()` serialization of the AST)

**Structural summary fields:**

| Field | Type | Description |
|-------|------|-------------|
| `file` | string | Path to the inspected file |
| `block_count` | int | Total top-level blocks (fragments + prompts + namespaces + comments) |
| `str_frags` | list[string] | Names of all `StrFrag` definitions |
| `role_frags` | list[string] | Names of all `RoleFrag` definitions |
| `prompts` | list[string] | Names of all prompt/chart definitions |
| `namespaces` | list[string] | Names of all `Namespace` blocks (e.g., `"env"`, `"sys"`, `"resp"`) |

## When to Use This Tool

Reach for `acdl_inspect` when the user asks any of these:

- "What fragments are defined in this spec?"
- "Which prompts exist in the harness?"
- "What namespaces does DeverinoChatLoop declare?"
- "How many blocks are in deverino_react.acdl?"
- "Compare the fragment inventories of two .acdl files"
- "Does this .acdl file have a ConversationTurn fragment?"

## When NOT to Use This Tool

- **ACDL syntax questions** — use the `acdl-syntax` skill (syntax reference,
  conventions, gotchas)
- **Architecture documentation** — use the `deverino-react-acdl` skill
  (describes the Deverino loop architecture, traceability to Python sources)
- **Reading raw file content** — use `read_file` for line-by-line inspection
- **Parsing a fragment's body** — the structural summary lists names, not
  bodies. For detailed body inspection, examine the `acdl_ast` artifact

## The `acdl_ast` Artifact

The `acdl_ast` artifact contains the full typed AST serialized via `to_dict()`.
Each node is a dict with a `_type` field identifying the node class
(e.g., `"_type": "ConditionalBlock"`). This is useful for:

- Finding control flow structure (If/ElseIf conditions, ForEach iterables,
  Switch expressions) — these are typed `Comparison`, `BinaryOp`, `Identifier`,
  `ContextVar`, etc.
- Tracing which fragments a prompt invokes (look for `FragInvocation` nodes)
- Inspecting namespace bindings (look for `NamespaceBinding` nodes with
  `name` and `type_expr` fields)

**Token efficiency:** typed nodes are ~40% smaller than raw token lists in
JSON output. Prefer the `acdl_ast` when you need structural detail beyond
the summary.

## Related Skills

- **`acdl-syntax`** — syntax reference, conventions, gotchas for writing ACDL
- **`deverino-react-acdl`** — architecture documentation for the Deverino
  ReAct loop, mapping ACDL constructs to Python source locations
