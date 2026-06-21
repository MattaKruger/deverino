# Spec: Token Efficiency Across the Agentic Harness

**Date**: 2026-06-21
**Status**: draft (post-review)

## Context

The harness makes LLM calls in several independent paths:

1. **Primary chat agent** — every user turn flows through PydanticAI with a large system prompt
2. **GoalRunner ReAct loop** — every iteration (up to 50) makes a structured decision call
3. **Sub-agent spawner** — each sub-agent inherits the full persona + dual context maps
4. **Distiller** — every context-map cycle makes its own LLM call with events payload + current map
5. **Reflexion** — the refine pass runs a separate judge LLM call
6. **Skill compiler** — background compilation makes LLM calls per skill (one-time, cached by mtime)

Each path constructs its own prompt, and several carry redundant or oversized content. The system prompt alone is 4000–9000 tokens (SOUL ~1200, context map ~1024, skill catalog ~500, tool schemas ~3000, state ~300).

In the GoalRunner path, the decision prompt includes a full serialized JSON dump of all tool schemas — 2000–5000 tokens — **per iteration**. Critically, the GoalRunner `Agent` is constructed *without* `tools=` (only the primary chat agent registers them). The JSON dump in the prompt text is the model's **only** source of tool schemas for goal execution.

A 30-iteration goal run burns ~60K–150K tokens on tool schemas alone. Sub-agents burn 3K–8K on their system prompt before the first tool call. The Distiller sends the full current map context (1K–2.5K tokens) on every cycle.

## Problem

Seven concrete inefficiencies identified through code inspection:

1. **GoalRunner Agent has no registered tools** (`goal_runner.py:903-915`). Unlike the primary chat agent (`pydantic_runtime.py:371`), the decision Agent is built without `tools=`. The tools JSON in `_build_decision_prompt` is the **only source of tool schemas**. It cannot simply be removed — tools must first be registered on the Agent.

2. **SOUL.md is instructionally sparse**. ~1200 tokens (182 lines) with substantial expository prose. §9.1 ("Handling Tool Results") duplicates content that `_with_tool_policy()` already injects (lines 160-162 vs `pydantic_runtime.py:682-701`).

3. **Sub-agent spawner has no token compaction** (`v2/wiring.py:367-468`). Each sub-agent receives the full persona file, a persona-level context map, and a project-level context map with no compression or budget control.

4. **Distiller sends full current map context** (`distiller.py:35-59`). `_render_current_map()` renders all map entries with full summaries. For maps with 50+ entries, this adds 1K–2.5K tokens per cycle.

5. **Chat history loss on pruning**. `prune_message_history()` drops entire turns when over budget. No summarization fallback preserves *what happened*.

6. **Inconsistent token estimation**. Chat path uses `len() // 4`; GoalRunner/Cartographer use `tiktoken` with `cl100k_base`.

7. **Skill catalog preamble is verbose** (150 tokens) and partially duplicates SOUL.md §5.1.

## Proposed Solution

Seven changes across three phases.

### Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                    SYSTEM PROMPT (per session, cached)            │
│                                                                  │
│  ┌──────────────┐  ┌──────────┐  ┌────────────────────────────┐  │
│  │ SOUL-compact │  │ State    │  │ Context Map (≤1024 tokens)  │  │
│  │ ~500 tokens  │  │ ~300 tkn │  │ + skill catalog             │  │
│  └──────────────┘  └──────────┘  └────────────────────────────┘  │
│                                                                  │
│  ✅ Primary Agent: tools registered via Agent(tools=...)          │
│  ✅ Sub-Agent: compact persona-only, no dual map duplication     │
│  ✅ GoalRunner: tools registered + compact history               │
├──────────────────────────────────────────────────────────────────┤
│                ITERATION / CALL PROMPT (per turn)                 │
│                                                                  │
│  GoalRunner: compact event summary + "choose next action"        │
│  Chat:       user message + compressed (not dropped) history     │
│  Distiller:  pre-filtered events + down-sampled current map      │
│                                                                  │
│  ❌ No full tool schema JSON dump (tools are on the Agent)       │
│  ❌ No full current map context (down-sampled to keys+recent)    │
│  ❌ No duplicate tool policy (§9.1 removed from SOUL)            │
└──────────────────────────────────────────────────────────────────┘
```

---

### Phase 1 — Stop the bleeding (high-impact, low-risk)

**1.1 Register tools on GoalRunner Agent, then drop prompt JSON**

File: `harness_poc/core/runtime/goal_runner.py`

**Problem**: The GoalRunner Agent at line 903 has no `tools=` parameter. The tools JSON in the decision prompt is the model's sole source of tool awareness.

**Fix**: Two changes:
1. Add `tools=` to the Agent construction in `_decide_next_action_async` (line 903), mirroring `build_primary_agent()`:
   ```python
   from harness_poc.core.runtime.pydantic_runtime import build_skill_tools
   agent = Agent(
       model,
       output_type=PromptedOutput(GoalAction, ...),
       system_prompt=self._goal_system_prompt(goal),
       tools=build_skill_tools(app_state.skill_runner),  # NEW
       output_retries=2,
   )
   ```
2. Remove the tools JSON dump from `_build_decision_prompt` (lines 944-945):
   ```python
   # REMOVE:
   "## Available Tools",
   json.dumps(tools, indent=2, sort_keys=True),
   ```
   Replace with a compact name-only listing as a safety net:
   ```python
   "## Available Tools: "
   + ", ".join(sorted(t.get("function", {}).get("name", "") for t in tools)),
   ```

**Estimated savings**: 2000–5000 tokens per goal iteration (40K–200K tokens per 20-iteration run).

**Risk**: When tools are registered on the Agent, PydanticAI routes their schemas through the API `tools` parameter (confirmed: DeepSeek's `DeepSeekProvider` supports this natively). The compact name-only listing is a safety net — it can be dropped after validation but keeps the model aware of available tool names if the API-level registration behaves unexpectedly.

**Validation**: `test_goal_runner_tool_awareness` — assert the agent can still select the correct tool given a scenario.

---

**1.2 Create SOUL-compact.md variant**

File: `harness_poc/system_prompts/SOUL-compact.md` (new)

Reduce SOUL.md from ~1200 to ~500 tokens. Remove:
- Expository "I am" framing ("I am a language model running inside a harness...")
- §3.1 "Voice" and §3.2 "How I Structure Responses" → move to persona files
- §9.1 "Handling Tool Results" → already duplicated by `_with_tool_policy()`

Keep:
- §2 Operating Principles (compact: name + 1-line essence)
- §4 Runtime Self-Model (architecture facts, tool execution model)
- §5 Knowledge & Learning (skill loading instructions)
- §10 What I Am Not (boundary definitions)

Config: Add an **optional override** key so existing users are unaffected:

```yaml
paths:
  soul: harness_poc/system_prompts/SOUL.md           # unchanged (backward-compat)
  soul_compact: harness_poc/system_prompts/SOUL-compact.md  # NEW: optional
```

`app_factory.py` logic: if `soul_compact` is set and the file exists, use it; otherwise, fall back to `soul`. This is a zero-risk rollout — existing deployments keep the full SOUL.

**Estimated savings**: ~700 tokens per session + ~120 tokens from the §9.1 dedup.

---

**1.3 Trim skill catalog preamble**

File: `harness_poc/core/skills/skill_catalog.py`

The `<available_skills>` preamble (lines 61-83) is ~150 tokens and partially duplicates SOUL.md §5.1. Collapse to 2 lines:

```python
catalog = (
    "## Skills\n"
    "Load relevant skills with skill_view(name). Always load developer-pedagogy. "
    "Update skills with skill_manage if they're missing steps or outdated.\n\n"
    "<available_skills>\n" + "\n".join(lines) + "\n"
    "</available_skills>\n"
)
```

**Estimated savings**: ~100 tokens per system prompt rebuild.

---

**1.4 Deduplicate continue prompt in GoalRunner**

File: `harness_poc/core/runtime/goal_runner.py`

Move the "Continue working toward the goal..." text (lines 853-864) from the per-iteration user message into the system prompt (`_goal_system_prompt`, line 1192). It's identical every iteration and adds ~30 tokens each time. In the system prompt it's cached once.

**Estimated savings**: ~30 tokens per iteration (×30 iterations = 900 tokens per goal run).

---

### Phase 2 — Smarter compression

**2.1 Compress sub-agent system prompt**

File: `harness_poc/v2/wiring.py`

The `_HarnessSpawner.spawn()` method (line 367) builds sub-agent system prompts with:
1. Full persona file text
2. Persona-specific context map block
3. Project-level context map block

Only #2 (persona-specific) adds unique value. The project-level map (#3) is already available through the primary agent and adds redundancy.

Changes:
- Drop the project-level context map from sub-agent prompts (keep persona-level only)
- Add `sub_agent_prompt_max_tokens: int = 4000` to `RuntimeConfig`
- After building `system_prompt` (persona + persona-map), estimate tokens and truncate the map block if over budget (truncate map before persona — map is supplementary)
- Truncation: drop lowest-priority entries from the rendered map until under budget

Config addition (`harness.yaml`):

```yaml
runtime:
  sub_agent_prompt_max_tokens: 4000
```

**Estimated savings**: 2K–5K tokens per sub-agent spawn.

---

**2.2 Down-sample Distiller's current map context**

File: `harness_poc/core/context_map/distiller.py`

`_render_current_map()` (line 35) sends the full current map (all entries with summaries) to every Distiller call. Change to send only:
- `prior_keys`: list of ALL entry keys (compact — still needed for Rule 1 in the distiller prompt)
- `recent_entries`: last 10 entries sorted by `last_updated` desc (explicit sort)
- `high_priority_entries`: entries with `priority >= 0.7`, deduplicated against `recent_entries`

The LLM needs orientation about what's known, not a full replica of the map.

**Estimated savings**: 500–1500 tokens per distiller cycle.

---

**2.3 CopT pre-filter for Distiller events**

File: `skills/context-map-materializer/skill.py` (NOT `distiller.py` — needs DB access for `materialization_count` filtering)

Before calling the LLM, use the already-loaded CopT embedding model to filter events that are near-duplicates of already-mapped content:

```python
def _prefilter_events(
    events: Sequence[ContextMapEvent],
    current_map: Sequence[MapEntry],
    threshold: float = 0.92,
) -> list[ContextMapEvent]:
    """Remove events whose content is near-duplicate of an existing map entry."""
    ...
```

Only filter against entries with `materialization_count > 1` (confirmed knowledge). Single-appearance entries are too new to safely suppress.

Config: use `materializer_copt_threshold` from `harness.yaml` (already set to 0.92).

**Estimated savings**: 30–50% of distiller input tokens per cycle.

---

**2.4 Progressive chat history compression**

File: `harness_poc/core/runtime/message_history.py`

Add `compress_message_history()` that creates a deterministic summary of older turns before hard-pruning:

1. When `estimate_message_tokens(messages) > max_tokens * 0.8`:
2. Split into older turns (beyond `recent_turns`) and recent turns
3. For each older turn: extract user prompt text (first 200 chars) + tool names called + whether output contained errors
4. Build a `[Compressed history]` summary block
5. **Prepend** the summary to the first user message of the recent turns (NOT as a separate message — avoids consecutive-user-message API rejection)
6. Only hard-prune if still over budget

**Estimated savings**: Preserves 2–3× more historical context within the same token budget.

---

**2.5 Distiller prompt compact variant**

File: `harness_poc/core/context_map/prompts/distiller_v2_compact.md` (new)

Reduce `distiller_v2.md` (~700 tokens) by dropping explanatory prose. Keep the schema contract and compact observation_type reference table.

Config (backward-compatible):

```yaml
distiller:
  prompt_template: distiller_v2               # unchanged default
  prompt_template_compact: distiller_v2_compact  # NEW: optional override
```

---

### Phase 3 — Consistency & observability

**3.1 Unified token estimation with tiktoken**

File: `harness_poc/core/runtime/message_history.py`

Replace `TOKEN_CHAR_RATIO = 4` with `tiktoken.get_encoding("cl100k_base")`. Use the same `_get_encoder()` pattern already in `cartographer.py` and `goal_runner.py`.

**Note**: DeepSeek uses a slightly different tokenizer than `cl100k_base`. The estimation error (~5–15%) is acceptable and significantly better than the current `/4` heuristic (~30–50% error).

---

**3.2 Cross-corpus rendering cache**

File: `harness_poc/app_factory.py`

Add mtime-based caching to `_render_cross_corpus()` (same pattern as `build_skill_catalog()`). Cache invalidates when corpus cycle changes.

---

**3.3 Skip context map rendering for small maps**

File: `harness_poc/v2/wiring.py`

When the context map has fewer than 3 entries or all entries are stale (last_seen_cycle < current_cycle - 10), skip the context map block entirely. An empty or stale map provides no actionable orientation.

---

**3.4 Token observability**

Add a `@tokens` REPL command that prints:
- Current session token totals (input/output/billable)
- Per-goal token breakdown
- System prompt token estimate (SOUL + context map + skill catalog + state)
- Context map token usage (% of budget)

File: `harness_poc/repl.py`

---

## Files

| File | Change |
|---|---|
| `harness_poc/core/runtime/goal_runner.py` | Register tools on Agent + drop JSON dump + move continue prompt to system |
| `harness_poc/system_prompts/SOUL-compact.md` | **New** — compact SOUL variant |
| `harness_poc/core/skills/skill_catalog.py` | Compact preamble |
| `harness_poc/v2/wiring.py` | Compress sub-agent prompt + skip small maps |
| `harness_poc/core/context_map/distiller.py` | Down-sample map context + CopT pre-filter |
| `harness_poc/core/context_map/prompts/distiller_v2_compact.md` | **New** — compact distiller prompt |
| `harness_poc/core/runtime/message_history.py` | Progressive compression + tiktoken unification |
| `harness_poc/app_factory.py` | Soul compact toggle + cross-corpus cache |
| `harness_poc/repl.py` | `@tokens` command |
| `harness.yaml` | Add `soul_compact`, `sub_agent_prompt_max_tokens`, `prompt_template_compact` keys |
| `tests/test_token_efficiency.py` | **New** — token budget + compression + regression tests |

No database migrations. Breaking changes: none (all new config keys are optional with defaults preserving current behavior).

---

## Risks & Open Questions

1. **GoalRunner tool registration may change decision behavior.** The model currently sees tool descriptions inline in the prompt; after registration, they're sent via the API `tools` parameter. The compact name listing is a safety net. If decision quality drops, keep the name listing and add brief 1-line descriptions without full JSON schemas.

2. **SOUL-compact behavioral regression.** The full SOUL.md uses "embodiment" framing (values, not instructions). A compact variant may lose this. Mitigation: run a side-by-side eval with 10+ representative tasks comparing response quality, tool selection accuracy, and error handling. Keep `soul_compact` as an opt-in toggle until validated.

3. **CopT pre-filter false positives at 0.92 threshold.** Novel events that happen to use similar language to existing entries could be suppressed. Mitigation: only filter against entries with `materialization_count > 1` (confirmed knowledge). Single-appearance entries are too fragile to use as dedup targets.

4. **Compressed chat history fidelity.** Deterministic string extraction of tool names and statuses may misrepresent complex tool results. Mitigation: prefix with `[compressed history — see recent events for full detail]` and never compress the most recent N turns.

5. **tiktoken encoding mismatch.** `cl100k_base` is OpenAI's tokenizer. DeepSeek uses a different one. Estimation error (~5–15%) is acceptable for budget enforcement but may cause subtle off-by-one in edge cases. Mitigation: document the known mismatch; switch to DeepSeek-compatible encoding if they publish one.

6. **`output_retries=2` doubles prompt tokens on parse failure.** The GoalRunner Agent uses `PromptedOutput` with retries. Each retry sends the full prompt again. Mitigation: reduce `output_retries` to 1 if the first-attempt parse success rate is high (>90%). Track parse-failure rate as an observability metric.

---

## Testing Strategy

File: `tests/test_token_efficiency.py`

### Required test cases

| Test | What it validates | Priority |
|---|---|---|
| `test_goal_runner_tool_awareness` | Agent correctly selects tools with registration + compact listing | **P0** |
| `test_goal_runner_prompt_under_budget` | Decision prompt with 10 tools + 50 events stays under N tokens | P0 |
| `test_goal_runner_no_duplicate_tool_json` | Verify tools JSON is absent from prompt after tool registration | P0 |
| `test_tiktoken_vs_heuristic_accuracy` | Compare `/4` vs `tiktoken` on code, JSON, prose samples | P1 |
| `test_compress_message_history_preserves_semantics` | Important tool outcomes survive compression | P1 |
| `test_copt_prefilter_recall_and_precision` | Known-duplicates filtered; known-novel events pass through | P1 |
| `test_soul_compact_behavioral_regression` | Agent responses with SOUL vs SOUL-compact on 5 representative tasks | P1 |
| `test_distiller_input_under_budget` | Distiller prompt + down-sampled map + events < token budget | P1 |
| `test_sub_agent_prompt_under_budget` | Sub-agent system prompt < configured max | P1 |
| `test_prune_compresses_not_drops` | More history preserved with compression than raw pruning | P2 |
| `test_cross_path_token_consistency` | Chat, GoalRunner, Cartographer agree on token counts for same text | P2 |

### Test infrastructure helpers

- `assert_token_budget(text, max_tokens)` — fails with diff showing what exceeds budget
- `prompt_snapshot_test(text)` — saves golden prompt; fails if size or content regresses
- `count_tokens_tiktoken(text)` — shared helper used by all paths

---

## Implementation Phases

### Phase 1 — Stop the bleeding (~100 lines, 1 new file)

| # | Task | Files | Lines |
|---|---|---|---|
| 1.1 | Register tools on GoalRunner Agent; drop JSON dump; add compact name listing | `goal_runner.py` | ~15 |
| 1.2 | Create SOUL-compact.md; add `soul_compact` config toggle | `SOUL-compact.md`, `harness.yaml`, `app_factory.py` | ~120 content + ~10 code |
| 1.3 | Trim skill catalog preamble | `skill_catalog.py` | ~5 |
| 1.4 | Move GoalRunner continue prompt to system prompt | `goal_runner.py` | ~3 |
| 1.5 | Tests: tool awareness + prompt budget | `tests/test_token_efficiency.py` | ~80 |

### Phase 2 — Smarter compression (~150 lines, 1 new file)

| # | Task | Files | Lines |
|---|---|---|---|
| 2.1 | Compress sub-agent prompt (drop project-level map) | `v2/wiring.py` | ~15 |
| 2.2 | Down-sample distiller current map context | `distiller.py` | ~30 |
| 2.3 | CopT pre-filter in distiller | `distiller.py` | ~40 |
| 2.4 | Progressive chat history compression | `message_history.py` | ~50 |
| 2.5 | Distiller prompt compact variant | `prompts/distiller_v2_compact.md` | ~60 content |
| 2.6 | Tests: compression + sub-agent + distiller budgets | `tests/test_token_efficiency.py` | ~60 |

### Phase 3 — Consistency & observability (~80 lines)

| # | Task | Files | Lines |
|---|---|---|---|
| 3.1 | Unified tiktoken estimation in message_history | `message_history.py` | ~15 |
| 3.2 | Cross-corpus rendering cache | `app_factory.py` | ~20 |
| 3.3 | Skip context map for small/stale maps | `v2/wiring.py` | ~5 |
| 3.4 | `@tokens` REPL command | `repl.py` | ~30 |
| 3.5 | Tests: cross-path consistency | `tests/test_token_efficiency.py` | ~30 |

### Phase 4 (follow-up) — Observability & tuning

| # | Task |
|---|---|
| 4.1 | Track parse-failure rate on GoalRunner Agent; consider reducing `output_retries` |
| 4.2 | Skill compiler token budget (out of scope for this spec — one-time cost, cached) |
| 4.3 | `developer-pedagogy` skill body size audit (force-loaded every session per SOUL.md §5.1) |
