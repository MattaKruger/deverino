# System Context Self-Reasoning — Test Scenarios

Scenarios where the agent uses `acdl_inspect` to reason about its **own** runtime
infrastructure — the system prompt assembly pipeline, context injection, turn
history rendering, tool budgets, and namespace variable provenance.

These go beyond structural queries. They test whether the agent builds a causal
model: "I know what I'm made of, and I can trace where each piece comes from."

---

## 1. System prompt provenance

**Prompt:** "Inspect deverino_react.acdl and explain how my system prompt is
assembled. What fragments go into it, in what order, and what gates their
inclusion?"

**What the agent should discover:**

The `DeverinoChatLoop` S block assembles 5 fragments in order:

```
S: {
    Frag SoulCharter          // always included — agent identity
    Frag StateBlock           // always included — durable state
    If sys.context_map != none {
        Frag ContextMapBlock  // CONDITIONAL — only when PEEK is active
    }
    Frag SkillCatalogBlock     // always included — available skills
    Frag ToolPolicyBlock       // always included — tool usage rules
}
```

**Expected reasoning:**

- The agent identifies that 4 of 5 fragments are unconditional, 1 is gated
  by `sys.context_map != none`
- The agent explains the layering: identity first, then state, then
  orientation (conditional), then capabilities, then constraints
- The agent connects this to the `acdl-tooling` skill's mention of the
  `acdl_ast` artifact and traces the `FragInvocation` nodes
- Bonus: agent checks its current session — does `sys.context_map` have a
  value? If so, the ContextMapBlock is active right now.

**Success criteria:**
- All 5 fragments identified in correct order
- Conditional inclusion of ContextMapBlock explained
- Agent connects the spec to its own runtime state ("am I running with PEEK?")
- No hallucinated fragments

---

## 2. "What am I made of?" — recursive self-description

**Prompt:** "Using the ACDL spec and your own runtime state, describe exactly
what context is in your system prompt right now. What's the SOUL? What's in
my STATE? What skills are in your catalog? What tool policies constrain you?"

**What the agent should do:**

1. Call `acdl_inspect` to understand the assembly structure (scenario 1)
2. Call `read_memory` to check `sys.soul_charter`, `sys.project_state`,
   `sys.session_state`, `sys.context_map`, `sys.available_skills`
3. Synthesize: "My system prompt is assembled from 5 layers. Layer 1 is the
   SOUL charter (currently loaded, 403 lines). Layer 2 is your project and
   session state (currently: ...). Layer 3 is the PEEK context map
   (currently: present/absent). Layer 4 is the skill catalog listing N
   knowledge skills. Layer 5 is the tool policy (max 10 rounds, etc.)."

**Expected behavior:**
- Agent uses `acdl_inspect` for the structural blueprint
- Agent uses `read_memory` for the runtime values
- Agent correlates: spec says "5 layers" → runtime says "layer 3 is active"
- Agent reports concretely, not abstractly

**Success criteria:**
- Both tools called (architectural blueprint + runtime state)
- Output is concrete: actual values, not templates
- Agent distinguishes between "the spec says X should be there" and
  "I checked and X is currently: Y"

---

## 3. Turn history self-model

**Prompt:** "How is our conversation history rendered? Look at the
ConversationTurn fragment and explain what I see vs what the model sees."

**What the agent should discover:**

The `ConversationTurn[@t]` RoleFrag renders each turn as:

```
If env.user_input[@t] != none   → U: env.user_input[@t]        // user message
If resp.tool_calls[@t] != none  → A: { reasoning + tool calls } // model actions
If resp.answer[@t] != none      → A: resp.answer[@t]            // model text
If resp.observations[@t] != none → ForEach obs: ... → U: obs    // tool results
```

**Expected reasoning:**

- The agent explains that each turn can have 0–4 role blocks depending on
  what happened: a text-only exchange has blocks 1+3, a tool-using exchange
  has blocks 1+2+4 (possibly also 3), an observation has block 4
- The agent notes the rendering asymmetry: tool calls and answers both
  appear as assistant (`A:`) but observations appear as user (`U:`) —
  this is how the model receives tool results as "user" input
- The agent connects this to the DeverinoChatLoop history truncation:
  only last 6 turns rendered, older turns dropped

**Success criteria:**
- Agent identifies the 4 conditions and their role assignments
- Agent explains the A:/U: asymmetry and its purpose
- Agent connects to truncation policy (ToolBudgetBlock, TruncationPolicy)
- Agent notes that the `@t` parameter means this fragment is instantiated
  per-turn via `Frag ConversationTurn[@t]`

---

## 4. Tool budget self-governance

**Prompt:** "What constraints does the ACDL spec place on your tool usage?
Read the relevant fragments and tell me my own limits."

**What the agent should discover:**

From ToolBudgetBlock and TruncationPolicy fragments (and DeverinoChatLoop
U block):

- Max 10 consecutive tool rounds (circuit breaker)
- 3 semble_search calls per run
- Per-tool duplicate-call guard active
- 24000 token chat history budget
- 6 recent turns retained, older dropped without summarization

**Expected reasoning:**

- Agent calls `acdl_inspect`, then drills into `acdl_ast` to find
  ToolBudgetBlock and TruncationPolicy StrFrag bodies
- Agent reads the string literals in those fragments
- Agent reports each constraint with its source fragment
- Bonus: agent checks its own `tool_call_counts` to report current usage:
  "I've made 2 tool calls this session, 8 remaining before circuit breaker"

**Success criteria:**
- All 5 constraints identified
- Each constraint traced to its source fragment
- Agent distinguishes between spec-defined limits and runtime state

---

## 5. Goal loop vs chat loop — operational self-model

**Prompt:** "Compare DeverinoChatLoop and DeverinoGoalLoop from the ACDL spec.
If you were running in goal mode right now instead of chat mode, what would
be different about your context?"

**What the agent should discover:**

| Aspect | Chat loop | Goal loop |
|--------|-----------|-----------|
| System prompt layers | 5 layers | 5 layers + GoalHeader + autonomous policy text |
| Namespace env | 6 bindings | 6 bindings + goal_objective, max_iterations, max_tokens, max_seconds |
| Namespace sys | 9 bindings | 9 bindings + event_history, iteration, total_tokens_used |
| Namespace resp | 5 bindings | 5 bindings + is_complete, final_answer |
| Turn history | ConversationTurn (last 6) | EventMappedTurn (full event history) |
| Termination | Until user ends session | Until is_complete=true or budget exhausted |
| Evaluation | None | GoalEvaluated after each cycle |

**Expected reasoning:**

- Agent calls `acdl_inspect` twice or drills into `acdl_ast` for both prompts
- Agent produces a structured comparison (table or bullet list)
- Agent explains the semantic difference: chat mode is open-ended
  conversation, goal mode is structured iteration with explicit completion
  check
- Agent notes the EventMappedTurn fragment maps typed `BaseEvent` instances
  to conversation roles — this is how goal runner's event-sourced state
  becomes LLM-readable context

**Success criteria:**
- At least 5 differences identified across namespaces, fragments, and
  control flow
- Agent explains the event-sourcing pattern (EventMappedTurn mapping)
- Agent connects to `deverino-react-acdl` skill for the Python source
  traceability

---

## 6. Namespace variable provenance

**Prompt:** "Where does each variable in the `sys` namespace come from? Trace
every binding in DeverinoChatLoop's sys namespace to its Python source."

**What the agent should do:**

The `sys` namespace has 9 bindings:

| Variable | Provenance |
|----------|-----------|
| `sys.soul_charter` | `harness_poc/system_prompts/SOUL.md` — loaded at startup |
| `sys.project_id` | `harness.yaml` `project.id` |
| `sys.project_state` | `harness_poc/core/state.py` `build_state_context()` — durable STATE |
| `sys.session_state` | `harness_poc/core/state.py` `build_state_context()` — session STATE |
| `sys.context_map` | `harness_poc/app_factory.py:118-124` — PEEK materialization |
| `sys.available_skills` | `harness_poc/core/skills/skill_catalog.py` `build_skill_catalog()` |
| `sys.tool_policy` | `harness_poc/core/runtime/pydantic_runtime.py` `_with_tool_policy()` |
| `sys.session_id` | Durable session identifier from database |
| `sys.config.*` | `harness.yaml` LLM config section |

**Expected reasoning:**

- Agent calls `acdl_inspect`, extracts sys namespace bindings
- Agent cross-references with `deverino-react-acdl` skill which has the
  architecture traceability table
- Agent produces a mapping table
- Agent notes which variables are static (config, SOUL) vs dynamic
  (state, context_map, available_skills) vs derived (tool_policy)
- Agent explains that `sys.context_map != none` is the gate on
  ContextMapBlock inclusion — this variable's presence/absence
  controls whether the agent sees its own orientation cache

**Success criteria:**
- All 9 bindings traced to a source
- Agent distinguishes static/dynamic/derived categories
- Agent connects the context_map binding to the conditional fragment
  inclusion (closing the loop with scenario 1)

---

## 7. "What would break?" — resilience reasoning

**Prompt:** "If I deleted the SoulCharter fragment from deverino_react.acdl,
what would happen to your system prompt? Walk through the impact."

**What the agent should discover:**

By inspecting DeverinoChatLoop's S block:
```
S: {
    Frag SoulCharter      // <-- THIS IS GONE
    Frag StateBlock
    If sys.context_map != none { Frag ContextMapBlock }
    Frag SkillCatalogBlock
    Frag ToolPolicyBlock
}
```

**Expected reasoning:**

- The agent notes that SoulCharter is the first fragment in the S block
  and has no conditional gate — it's always included
- If deleted from the ACDL file, the `Frag SoulCharter` invocation would
  fail at render time (fragment not found)
- The agent explains that ACDL is a specification language — deleting a
  fragment from the spec doesn't delete the actual SOUL.md file or change
  the runtime behavior directly, BUT:
  - Any renderer consuming the ACDL spec would break
  - The architectural documentation becomes stale
  - The `acdl_inspect` tool would report 8 StrFrags instead of 9
- The agent distinguishes between "the spec says X" and "the runtime does X"
  — the SOUL is loaded from `system_prompts/SOUL.md`, not from the ACDL spec

**Success criteria:**
- Agent identifies the fragment's position and unconditional inclusion
- Agent correctly distinguishes spec vs runtime: deleting from ACDL ≠
  deleting from the actual system prompt
- Agent notes the documentation/diagramming impact
- Agent explains what `acdl_inspect` would report differently

---

## 8. Self-modification reasoning

**Prompt:** "I want to add a new fragment called CodebaseContext that shows
the current git branch and recent commits. Where in the system prompt
assembly would you insert it, and what condition would gate it?"

**What the agent should do:**

1. Call `acdl_inspect` to see the current S block structure
2. Reason about the layer ordering:
   - SoulCharter (identity) → StateBlock (state) → ContextMapBlock
     (orientation) → SkillCatalogBlock (capabilities) → ToolPolicyBlock
     (constraints)
3. Propose insertion point: after StateBlock, before ContextMapBlock
   (codebase context is orientation, like PEEK)
4. Propose condition: `If sys.codebase_context != none` (mirroring the
   ContextMapBlock pattern)
5. Explain the namespace binding needed: add `codebase_context: string` to
   the `sys` namespace
6. Note that the harness would need corresponding Python code to populate
   `sys.codebase_context` — the ACDL spec declares the interface, the
   runtime fulfills it

**Expected reasoning:**

- Agent uses the existing 5-layer structure as a template
- Agent reasons by analogy: "ContextMapBlock is conditional orientation →
  CodebaseContext should be too"
- Agent follows the established pattern: namespace binding → conditional
  fragment invocation
- Agent identifies the boundary: ACDL declares what should exist, Python
  code makes it exist

**Success criteria:**
- Insertion point is justified by the layer semantics
- Condition pattern mirrors existing convention (ContextMapBlock)
- Agent identifies the namespace binding requirement
- Agent notes the Python-side implementation need (not just ACDL)

---

## Scenario matrix

| # | Scenario | Tools used | Self-model depth | Difficulty |
|---|----------|-----------|-----------------|------------|
| 1 | System prompt provenance | `acdl_inspect` + `acdl_ast` | Structural — knows the blueprint | Medium |
| 2 | "What am I made of?" | `acdl_inspect` + `read_memory` | Runtime — checks own state | Hard |
| 3 | Turn history self-model | `acdl_inspect` + `acdl_ast` | Behavioral — understands rendering | Medium |
| 4 | Tool budget self-governance | `acdl_inspect` | Constraint — knows own limits | Easy |
| 5 | Goal vs chat loop | `acdl_inspect` × comparison | Operational — knows modes | Hard |
| 6 | Namespace provenance | `acdl_inspect` + `acdl_ast` | Causal — traces variable origins | Hard |
| 7 | "What would break?" | `acdl_inspect` | Counterfactual — spec vs runtime | Medium |
| 8 | Self-modification | `acdl_inspect` + `acdl_ast` | Generative — proposes extensions | Hard |

---

## What makes these different from the structural scenarios

The `acdl-agent-tooling.md` scenarios test whether the agent can **use the tool**.
These scenarios test whether the agent can **reason about itself using the tool**.

The distinction:

| Structural scenarios | Self-reasoning scenarios |
|---------------------|-------------------------|
| "What fragments exist?" | "Which fragments form MY system prompt?" |
| "How many conditions compare against none?" | "What gates MY context map inclusion?" |
| "What namespaces are declared?" | "Where does MY session state come from?" |
| "Compare two files" | "How would I behave differently in goal mode?" |
| — | "What would break if a fragment was deleted?" |
| — | "Where should a new fragment go?" |

The self-reasoning scenarios require the agent to hold two models simultaneously:
1. The **ACDL spec** as a data structure (what `acdl_inspect` returns)
2. Its **own runtime** as the thing being described (what `read_memory` returns,
   what it knows from its system prompt, what it observes about its own behavior)

The synthesis of these two models is the capability being demonstrated.
