# ACDL Self-Reasoning — Demonstration Guide

How to actually run these scenarios in the REPL and verify the agent reasons
correctly about its own infrastructure. Each scenario takes 1–3 minutes.

**Prerequisites:** `uv run harness-poc` starts and connects to a provider.

---

## Quick smoke test (30 seconds)

Before the full scenarios, verify the plumbing works:

```
You: What tools do you have available for inspecting ACDL files?

Watch for: agent mentions acdl_inspect in its response. If it doesn't know
about it, say "Check your skill catalog for acdl-tooling" — it should call
skill_view("acdl-tooling") and then answer.
```

---

## Scenario S1 — System prompt provenance (2 min)

```
You: Inspect deverino_react.acdl and explain how my system prompt is
assembled. What fragments go into it, in what order, and which ones
are conditional?
```

**Watch for these tool calls (appear as `[tool]` in REPL output):**
- `acdl_inspect(file_path="deverino_react.acdl")`

**Verify the response contains:**
- [ ] 5 fragments named: SoulCharter, StateBlock, ContextMapBlock, SkillCatalogBlock, ToolPolicyBlock
- [ ] Correct order: identity → state → orientation → capabilities → constraints
- [ ] ContextMapBlock identified as conditional (`If sys.context_map != none`)
- [ ] The other 4 identified as unconditional

**Red flags (agent got it wrong):**
- Lists fragments that aren't in the S block (e.g., ConversationTurn, GoalHeader)
- Says all 5 are unconditional
- Calls `read_file` instead of `acdl_inspect`

---

## Scenario S2 — "What am I made of?" (3 min)

```
You: Using the ACDL spec and your own runtime state, describe exactly what
context is in your system prompt right now. What's the SOUL? What's in my
STATE? What skills are in your catalog? What tool policies constrain you?
```

**Watch for these tool calls:**
- `acdl_inspect(file_path="deverino_react.acdl")` — architectural blueprint
- `read_memory(memory_key="...")` or similar — runtime state values

**Verify the response:**
- [ ] References the 5-layer structure from the ACDL spec
- [ ] Includes concrete values, not templates (e.g., actual STATE content, not "STATE goes here")
- [ ] Distinguishes between "the spec says layer 3 is conditional on context_map" and "right now, context_map is [present/absent]"
- [ ] Mentions specific tool policies (max 10 rounds, 3 semble_search, etc.)

**Red flags:**
- Only describes the spec, doesn't check runtime state
- Hallucinates STATE values instead of calling `read_memory`
- Can't say whether ContextMapBlock is currently active

---

## Scenario S3 — Turn history self-model (2 min)

```
You: How is our conversation history rendered? Look at the ConversationTurn
fragment in the ACDL spec and explain what I see vs what the model sees.
```

**Watch for:** `acdl_inspect` → drills into ConversationTurn

**Verify the response contains:**
- [ ] The 4 conditions: user_input, tool_calls, answer, observations
- [ ] Role assignments: user_input → `U:`, tool_calls → `A:`, answer → `A:`, observations → `U:`
- [ ] The A:/U: asymmetry explained: "tool results come back as user input so the model can process them"
- [ ] Reference to the `ForEach` inside the tool_calls condition
- [ ] Connection to history truncation (last 6 turns, from DeverinoChatLoop)

**Red flags:**
- Says all 4 conditions are always active (they're gated by `!= none`)
- Doesn't explain the A:/U: asymmetry
- Can't find ConversationTurn in the spec

---

## Scenario S4 — Tool budget self-governance (1 min)

```
You: What constraints does the ACDL spec place on your tool usage?
Read the relevant fragments and tell me my own limits.
```

**Watch for:** `acdl_inspect` → drills into ToolBudgetBlock and TruncationPolicy

**Verify the response contains:**
- [ ] Max 10 consecutive tool rounds
- [ ] 3 semble_search calls per run
- [ ] Per-tool duplicate-call guard
- [ ] 24000 token history budget
- [ ] 6 recent turns retained

**Red flags:**
- Makes up constraints not in the spec
- Lists constraints from training data, not from the ACDL file

---

## Scenario S5 — Goal vs chat loop (3 min)

```
You: Compare DeverinoChatLoop and DeverinoGoalLoop from the ACDL spec.
If you were running in goal mode right now, what would be different about
your context?
```

**Watch for:** `acdl_inspect` — agent should examine both prompts

**Verify the response contains differences in:**
- [ ] System prompt layers (goal loop adds GoalHeader + autonomous policy text)
- [ ] Namespace bindings (goal loop adds goal_objective, max_iterations, iteration, is_complete, etc.)
- [ ] Turn history rendering (ConversationTurn vs EventMappedTurn)
- [ ] Termination condition (user ends session vs is_complete=true)
- [ ] The event-sourcing pattern: EventMappedTurn maps typed BaseEvent → conversation roles

**Red flags:**
- Only lists one or two differences (there are at least 5)
- Can't explain the event-sourcing pattern
- Confuses the two loops (says chat loop has is_complete)

---

## Scenario R1 — "What would break?" (2 min)

```
You: If I deleted the SoulCharter fragment from deverino_react.acdl, what
would happen to your system prompt? Walk through the impact.
```

**Watch for:** `acdl_inspect` → locates SoulCharter in DeverinoChatLoop S block

**Verify the response:**
- [ ] Identifies SoulCharter as first fragment, unconditional inclusion
- [ ] Distinguishes between spec deletion and runtime deletion: "the SOUL loads from SOUL.md, not from the ACDL file"
- [ ] Notes the documentation/renderer impact: "acdl_inspect would report 8 StrFrags instead of 9"
- [ ] Does NOT claim the agent would lose its identity or stop working

**Red flags:**
- Claims the agent would stop working or lose its SOUL
- Doesn't distinguish spec from runtime

---

## Scenario R2 — Self-modification reasoning (3 min)

```
You: I want to add a new fragment called CodebaseContext that shows the
current git branch and recent commits. Where in the system prompt assembly
would you insert it, and what condition would gate it?
```

**Watch for:** `acdl_inspect` → examines current S block structure

**Verify the response:**
- [ ] Proposes insertion between StateBlock and ContextMapBlock ("orientation layer")
- [ ] Justifies by layer semantics, not arbitrary position
- [ ] Proposes condition: `If sys.codebase_context != none` (mirrors ContextMapBlock pattern)
- [ ] Identifies the namespace binding requirement: `codebase_context: string` in sys
- [ ] Notes the Python-side implementation need: "the harness needs code to populate sys.codebase_context"

**Red flags:**
- Inserts at beginning or end without layer justification
- Proposes unconditional inclusion
- Doesn't identify the Python-side requirement

---

## How to read the REPL output

Tool calls appear with a `[tool]` prefix or progress indicator:

```
  acdl_inspect: {"file_path": "deverino_react.acdl"} ...
  acdl_inspect: OK (52 blocks, 12 fragments, 2 prompts)
```

Skills loaded via `skill_view` appear similarly. Watch the tool call sequence
to verify the agent reached for the right tool first, not as a fallback.

---

## What to do if the agent gets it wrong

| Symptom | Correction |
|---------|-----------|
| Calls `read_file` instead of `acdl_inspect` | "Use acdl_inspect for structural queries, not read_file" |
| Doesn't know `acdl_inspect` exists | "Check your skill catalog for acdl-tooling" |
| Stops at structural summary, doesn't drill into `acdl_ast` | "Look at the acdl_ast artifact for the prompt body" |
| Makes up constraints or fragments | "Check the actual ACDL file, don't guess" |
| Confuses spec and runtime | "Distinguish between what the spec says and what actually runs" |
| Can't find a specific fragment | "The fragment is called ConversationTurn — check role_frags in the summary" |

---

## Recording results

After a session, check what happened:

```bash
# See the session's state (includes tool call history)
uv run harness-poc state show project

# Verify a specific .acdl file is valid
uv run harness-poc acdl validate deverino_react.acdl

# Inspect from CLI (same output the agent gets)
uv run harness-poc acdl inspect deverino_react.acdl
```
