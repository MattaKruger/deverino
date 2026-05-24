# Plan: Automatic observation via post-turn harness hook

**Date**: 2026-05-24
**Status**: draft — under review / brainstorm

## Problem

The `observe` tool must currently be invoked manually — either by the user
or by an LLM that has been explicitly instructed to call it. This means
observations only accumulate when someone remembers to trigger them.

The goal is to make observation happen automatically as a side-effect of
normal conversation and goal runs, without relying on the LLM to decide
when to do it.

## What "automatic" means here

The harness fires `observe` (or an equivalent event write) on its own,
without an LLM tool call in the conversation turn. The LLM may still be
involved — to classify what's worth recording — but the *decision to
attempt observation* is made by the harness, not the model.

## Execution paths that need coverage

There are two independent paths through the runtime. Any hook solution
must address both or document why one is out of scope.

### Path 1: Chat (`handle_chat_input`)

File: `harness_poc/repl.py`, function `handle_chat_input` (L235–301)

```
user input
  → pydantic_runtime.stream_text()          # L247
      → _stream_text_async()
          → agent.iter() loop
              → ModelRequestNode  (LLM produces text + tool calls)
              → CallToolsNode     (harness executes tool calls)
  ← AgentRunResult(content, messages, usage)  # L252
  → messages stored, events published
  → streaming.on_finish()
```

After line 252, `response.messages` contains the full turn: every
`ToolCallPart`, `ToolReturnPart`, and `TextPart` produced. This is
the earliest point where the complete turn is available for inspection.

### Path 2: GoalRunner (`run_async`)

File: `harness_poc/core/runtime/goal_runner.py`, method `run_async` (L463)

The GoalRunner is a manual ReAct loop. It calls `skill_runner.execute_skill`
directly in `asyncio.to_thread` (L702) and receives a `SkillResult`. The
hook would slot in after each successful `SkillCompleted` event is published
(L709–717). Each iteration is a natural boundary.

## Three sub-approaches

### Approach A: Blind hooking

**Mechanism**: After each turn (or each tool result in the goal loop), emit
an `observe` call unconditionally with:

- `summary` — heuristically extracted (e.g., first file path found in
  tool output, first line of a search result, or a fixed template like
  `"Search result: <tool_name>"`)
- `detail` — the raw tool output, truncated to fit

**Where**: `handle_chat_input` after `stream_text` returns. Scan
`response.messages` for `ToolReturnPart` entries from high-signal tools
(`semble_search`, file reads). For each, call
`skill_runner.execute_skill("observe", ...)` directly.

**Signal quality**: Low. The summary is synthetic and the detail is raw
output — no semantic understanding of what was discovered or why it matters.
The context map fills up with low-quality entries that the cartographer
then has to evict.

**Cost**: None — no extra LLM call. Purely harness-side Python.

**Risk**: Context map noise. Many entries will be near-duplicates or
irrelevant. Eviction budget gets consumed faster.

**Verdict**: Cheapest to build, worst for map quality. Worth prototyping
only if the cartographer's distiller is trusted to filter aggressively.

---

### Approach B: Per-turn classifier LLM call

**Mechanism**: After each turn, feed the turn's content to a small,
cheap LLM call that extracts observations in structured form — essentially
a per-turn distiller. The output schema is already defined:
`DistilledBatch` in `harness_poc/core/context_map/schema.py`.

**Where**: A new function `_extract_turn_observations(response, session_id,
skill_runner, config)` called at the bottom of `handle_chat_input`, after
`streaming.on_finish`. It would:

1. Collect all `ToolReturnPart` content from `response.messages`
   plus `response.content` (the LLM's final text).
2. Build a compact prompt: "Here is a conversation turn. Extract any
   observations worth adding to the context map. Return a DistilledBatch."
3. Run via `chat_text()` (the no-tools model path already in
   `pydantic_runtime.py:707`) against a small/fast model.
4. Parse the returned `DistilledBatch`. For each `DistillerEntry`, call
   `skill_runner.execute_skill("observe", {observation_type, summary, detail})`.

**GoalRunner coverage**: Same pattern, but fires after each successful
skill result rather than after the whole turn. Each tool result is a
smaller, cheaper classification job.

**Signal quality**: High — equivalent to the cartographer's distiller,
just running per-turn instead of in batch.

**Cost**: One extra LLM call per conversation turn. On a fast/small model
(e.g., Haiku), this adds ~200–500ms and ~500–1000 tokens per turn. The
cost is paid whether or not the turn produced anything worth observing.

**Risk**:
- Latency is visible to the user (hook fires synchronously after `on_finish`
  but before the next prompt is offered in the TUI/REPL).
- Could be run async/in-background to hide latency — but then observation
  lag is ~1 turn behind.
- Partial duplication of the cartographer: if the cartographer also runs
  on the same event stream, some observations may be classified twice.

**Verdict**: Highest quality, highest cost. The right choice if observation
recency matters (i.e., you want the context map updated within the same
session rather than on the next cartographer run).

---

### Approach C: Per-tool interception with structural extraction

**Mechanism**: Intercept only high-signal tools at the point their results
return. Extract observations using structural patterns — not an LLM call.

Candidate tools and what can be extracted structurally:

| Tool | Extractable signal | `observe` type |
|---|---|---|
| `semble_search` | File paths + line refs from result chunks | `entity` |
| File read (via `file_tools`) | Module/class name from path | `entity` |
| `search_documents` | Document URI + chunk title | `entity` or `schema` |
| `consolidate_state` | State keys that were promoted | `result` |

**Where**: Two options:

1. Inside `_stream_text_async` at the `CallToolsNode` branch
   (L204 in `pydantic_runtime.py`). PydanticAI doesn't expose individual
   tool results here during streaming — you'd need to hook inside
   `_make_skill_tool` / `execute_skill_as_tool`.

2. In `SkillRunner.execute_skill` (skill_runner.py L126), add a
   post-execution callback hook: `on_skill_completed(skill_name, arguments,
   result)`. The caller (runtime or goal loop) registers a callback that
   fires after each skill execution.

Option 2 is cleaner — it's a single hook point that covers both the chat
path (via `execute_skill_as_tool`) and the goal loop (via `run_async`).

**Signal quality**: Medium. The summary and detail are templated, not
semantically derived. "Search result from semble_search for query X
returned file Y:Z" is factual but thin. Works best for `entity` type
observations where the file path is the observation.

**Cost**: None — pure Python pattern matching on tool output.

**Risk**:
- Structural patterns are brittle. `semble_search` output format changes
  → hook silently stops extracting anything.
- Only covers tools whose output has known structure. Tool results that
  are plain prose (e.g., a `delegate_task` summary) produce nothing.
- Requires maintaining a per-tool extraction registry.

**Verdict**: Good middle ground for a specific, bounded use case
(auto-recording file/entity references from search). Not a general solution.

---

## Relationship to the deterministic cartographer

The cartographer (`core/context_map/`) already solves the per-session
observation problem in batch:

1. Events accumulate in the database as `ContextMapEvent`s.
2. The cartographer's distiller LLM call reads those events and produces
   `DistilledBatch` entries.
3. `MapEntry` records are materialized into the context map.

A per-turn hook is the same pipeline at a finer cadence. The question is
whether **recency** (observations available within the same session) is
worth the cost over **batch** (observations available on the next
cartographer run).

If the cartographer runs at the end of each session or is triggered on
demand, a per-turn hook adds little architectural value — it just pays
more LLM cost for earlier availability of the same information.

If the cartographer only runs manually (as it currently does), a per-turn
hook would meaningfully change how fast the context map grows.

## Open design questions

1. **Synchronous vs. async hook**: Should the hook block the user (fire
   synchronously after `on_finish`) or run in a background thread? Blocking
   gives immediate context map updates but adds visible latency. Background
   gives no latency but observations lag one turn.

2. **Deduplication**: The hook will fire every turn. Multiple turns may
   observe the same entity. The `observe` skill and the cartographer both
   need a deduplication strategy (by key, by content hash, or by
   suppressing if entry already exists in the current map).

3. **Which turns trigger observation**: Every turn? Only turns where at
   least one search/read tool was called? Only turns where `response.content`
   exceeds a token threshold? A turn filter reduces noise and cost for
   approach B.

4. **Model for approach B**: The classifier call should use a cheaper model
   than the main runtime (e.g., Haiku vs. Sonnet/Opus). The `harness.yaml`
   config doesn't currently have a `classifier_llm` field. Either reuse the
   main LLM config or add a separate config key.

5. **Goal loop granularity**: Should the goal loop fire the hook after every
   skill, or once per goal run completion? Per-skill is noisier but faster;
   per-run is cheaper and cleaner.

6. **Callback hook in SkillRunner vs. call site**: Adding
   `on_skill_completed` to `SkillRunner` is cleaner than duplicating the
   hook at each call site (chat path + goal loop). But it adds coupling to
   the runner. Alternatively, the `execute_skill_as_tool` wrapper in
   `pydantic_runtime.py` and the `run_async` loop are the two call sites —
   two places to patch vs. one.

## Files that would be touched (approach B, synchronous)

| File | Change |
|---|---|
| `harness_poc/repl.py` | Call `_extract_turn_observations()` in `handle_chat_input` after `on_finish` |
| `harness_poc/core/runtime/goal_runner.py` | Call extractor after each successful `SkillCompleted` in `run_async` |
| `harness_poc/core/runtime/pydantic_runtime.py` | Add `chat_text`-based `extract_observations(content, tool_results)` helper |
| `harness_poc/core/context_map/schema.py` | Already has `DistilledBatch` — no change needed |
| `harness_poc/core/skills/skill_runner.py` | No change needed (called directly) |
| `harness.yaml` | Optionally: add `classifier_llm` config key |

## Files that would be touched (approach C, per-tool callback)

| File | Change |
|---|---|
| `harness_poc/core/skills/skill_runner.py` | Add `on_skill_completed` callback param to `execute_skill` |
| `harness_poc/core/runtime/pydantic_runtime.py` | Register callback in `execute_skill_as_tool` |
| `harness_poc/core/runtime/goal_runner.py` | Register callback in `run_async` |
| New module: `harness_poc/core/skills/observation_extractor.py` | Per-tool structural extraction logic + tool registry |

## Not in scope

- Changes to the `observe` skill itself (unless the fix plan for missing
  types lands first — see `2026-05-24-observe-missing-types-fix.md`).
- Changes to the deterministic cartographer pipeline.
- UI/TUI changes to surface observation activity to the user.
- Rate limiting or budgeting the observation calls (could be added later).
