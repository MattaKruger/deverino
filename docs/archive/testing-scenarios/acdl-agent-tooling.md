# ACDL Agent Tooling — Test Scenarios

Scenarios for verifying the agent can use `acdl_inspect` and the ACDL knowledge
skills to answer structural questions about the harness specification.

Each scenario lists the user prompt, expected tool calls, expected behavior,
and success criteria. Run these in the REPL (`uv run harness-poc`).

---

## 1. Fragment inventory

**Prompt:** "What fragments are defined in deverino_react.acdl?"

**Expected tool calls:**

1. `skill_view("acdl-tooling")` or direct knowledge from catalog
2. `acdl_inspect(file_path="deverino_react.acdl")`

**Expected behavior:**

- Agent returns the list of 9 `StrFrag` and 3 `RoleFrag` names
- Groups them by type (str_frags vs role_frags)
- Mentions block count (52) for context

**Success criteria:**

- Agent calls `acdl_inspect`, not `read_file`
- Output includes `SoulCharter`, `ConversationTurn`, `GoalEvaluationTurn`

---

## 2. Prompt structure query

**Prompt:** "What namespaces does DeverinoChatLoop declare?"

**Expected tool calls:**

1. `acdl_inspect(file_path="deverino_react.acdl")`

**Expected behavior:**

- The structural summary only lists top-level namespaces (`env`, `sys`, `resp`)
- Agent realizes the summary is insufficient for prompt-scoped namespaces
- Agent examines the `acdl_ast` artifact for DeverinoChatLoop's body
- Returns the 3 namespace names with their binding counts (env: 6, sys: 9, resp: 5)

**Success criteria:**

- Agent doesn't stop at the top-level summary
- Agent drills into the `acdl_ast` artifact
- Names match the actual ACDL: `user_input`, `soul_charter`, `answer`, etc.

---

## 3. Cross-file comparison

**Prompt:** "Compare the fragment inventories of deverino_react.acdl and
docs/acdl/deverino_loop_full.acdl. Which fragments are unique to each?"

**Expected tool calls:**

1. `acdl_inspect(file_path="deverino_react.acdl")`
2. `acdl_inspect(file_path="docs/acdl/deverino_loop_full.acdl")`

**Expected behavior:**

- Agent calls the tool twice (different file paths)
- Computes set differences for str_frags and role_frags
- Reports fragments unique to each file
- Notes if either file has fragments the other doesn't

**Success criteria:**

- Two separate tool calls, not one call with a wrong path
- Agent does set comparison, not just lists both inventories side by side

---

## 4. File not found

**Prompt:** "Inspect the file nonexistent.acdl for me."

**Expected tool calls:**

1. `acdl_inspect(file_path="nonexistent.acdl")`

**Expected behavior:**

- Tool returns `status: "failed"` with "File not found" message
- Agent reports the failure clearly — doesn't hallucinate contents
- Agent suggests checking the path or lists available `.acdl` files

**Success criteria:**

- Agent surfaces the failure, doesn't fabricate results
- Suggests corrective action (check path, list files)

---

## 5. Non-.acdl file rejection

**Prompt:** "Use acdl_inspect on harness.yaml."

**Expected tool calls:**

1. `acdl_inspect(file_path="harness.yaml")`

**Expected behavior:**

- Tool returns `status: "failed"` with "Not an .acdl file" message
- Agent reports that `harness.yaml` is not an ACDL file
- Agent doesn't try to parse it with another tool

**Success criteria:**

- Agent correctly relays the rejection message
- No fallback to `read_file` to parse it as ACDL

---

## 6. Knowledge skill synergy — syntax question

**Prompt:** "How do I write a ForEach loop in ACDL?"

**Expected tool calls:**

1. `skill_view("acdl-syntax")`

**Expected behavior:**

- Agent does NOT call `acdl_inspect` — this is a syntax question, not a
  structural inspection
- Agent loads `acdl-syntax`, finds the Control Flow section
- Returns the ForEach syntax with example

**Success criteria:**

- `acdl_inspect` is NOT called (tool misuse check)
- Answer includes correct syntax: `ForEach(var: expr) { body }`
- Answer references a concrete example from the skill

---

## 7. Knowledge skill synergy — architecture question

**Prompt:** "How does the system prompt get assembled in the Deverino chat loop?"

**Expected tool calls:**

1. `skill_view("deverino-react-acdl")`

**Expected behavior:**

- Agent does NOT call `acdl_inspect` — this is an architecture documentation
  question covered by `deverino-react-acdl`
- Agent loads the skill, finds the 5-layer concatenation description
- Returns the layer breakdown: SoulCharter → StateBlock → ContextMapBlock
  (conditional) → SkillCatalogBlock → ToolPolicyBlock

**Success criteria:**

- `acdl_inspect` is NOT called (correct tool selection)
- Answer matches the skill's documented architecture

---

## 8. Condition inspection via acdl_ast

**Prompt:** "In deverino_react.acdl, how many If conditions compare against 'none'?"

**Expected tool calls:**

1. `acdl_inspect(file_path="deverino_react.acdl")`

**Expected behavior:**

- Agent loads the `acdl_ast` artifact
- Searches for `Comparison` nodes with `operator: "!="` and a `right` node
  of `_type: "Identifier"` with `name: "none"`
- Counts occurrences across the full AST
- Reports the count with file locations (line numbers from block metadata if
  available, or structural context)

**Success criteria:**

- Agent uses `acdl_ast`, not the structural summary
- Correct count (4 conditions: 3 in ConversationTurn, 1 in DeverinoChatLoop S block)
- Agent explains WHERE they appear, not just the count

---

## 9. Control flow tracing

**Prompt:** "Trace the control flow in the ConversationTurn fragment. What
conditions gate which outputs?"

**Expected tool calls:**

1. `acdl_inspect(file_path="deverino_react.acdl")`

**Expected behavior:**

- Agent loads `acdl_ast` and locates the `ConversationTurn` RoleFrag
- Walks its body, identifying each `ConditionalBlock`:
  1. `If env.user_input[@t] != none` → `U: env.user_input[@t]`
  2. `If resp.tool_calls[@t] != none` → `A: { ... ForEach(call: resp.tool_calls[@t]) ... }`
  3. `If resp.answer[@t] != none` → `A: resp.answer[@t]`
  4. `If resp.observations[@t] != none` → `ForEach(obs: resp.observations[@t])`
- Describes the gating logic: user input only renders if present, tool calls
  and answers are independent conditions, observations trigger iteration

**Success criteria:**

- All 4 conditions identified
- Agent explains the semantics (conditions are independent, not if/else-if)
- ForEach structure inside condition 2 is noted

---

## 10. Namespace binding audit

**Prompt:** "Audit the DeverinoChatLoop namespace bindings. Are there any
variables referenced in the body that aren't declared in the namespaces?"

**Expected tool calls:**

1. `acdl_inspect(file_path="deverino_react.acdl")`

**Expected behavior:**

- Agent loads `acdl_ast`, locates DeverinoChatLoop
- Extracts all `NamespaceBinding` entries from the 3 namespace blocks
- Extracts all `ContextVar` references from the prompt body
- Cross-references: every `namespace.path` combination should have a
  corresponding binding
- Reports any unmatched references (should be zero for this spec)

**Success criteria:**

- Agent performs the cross-reference, not just lists both sides
- Reports "all references resolved" or specific mismatches
- Note: `sys.tool_policy` is referenced in ToolPolicyBlock fragment body,
  which is outside DeverinoChatLoop — agent should note cross-fragment
  references are not validated by this audit

---

## Scenario matrix

| #   | Scenario                 | Primary tool                        | Avoids misuse         | Difficulty |
| --- | ------------------------ | ----------------------------------- | --------------------- | ---------- |
| 1   | Fragment inventory       | `acdl_inspect`                      | `read_file`           | Easy       |
| 2   | Prompt-scoped namespaces | `acdl_inspect` + `acdl_ast`         | Stopping at summary   | Medium     |
| 3   | Cross-file comparison    | `acdl_inspect` ×2                   | Single call           | Medium     |
| 4   | File not found           | `acdl_inspect`                      | Hallucination         | Easy       |
| 5   | Non-.acdl rejection      | `acdl_inspect`                      | `read_file` fallback  | Easy       |
| 6   | Syntax question          | `skill_view("acdl-syntax")`         | `acdl_inspect`        | Easy       |
| 7   | Architecture question    | `skill_view("deverino-react-acdl")` | `acdl_inspect`        | Medium     |
| 8   | Condition search         | `acdl_ast` artifact                 | Structural summary    | Hard       |
| 9   | Control flow tracing     | `acdl_ast` artifact                 | Surface-level summary | Hard       |
| 10  | Namespace audit          | `acdl_ast` artifact                 | Unvalidated listing   | Hard       |

---

## Running the scenarios

Start the REPL and paste each prompt:

```bash
uv run harness-poc
```

For scenarios 8–10 (hard), the agent needs to work with the `acdl_ast` artifact
— a large JSON structure. These test whether the agent can navigate typed AST
nodes programmatically rather than relying on the pre-digested summary.

To verify the agent used the right tools, check the tool call log in the REPL
output (tool calls are emitted with `[tool]` prefix) or inspect the session
state afterward:

```bash
uv run harness-poc state show project
```
