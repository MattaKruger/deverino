# Plan Mode With Vespa-Indexed Outputs — v2

> **Revision rationale (v1 → v2):** Cross-referenced against the indexed LLM-paper corpus (SDOF, SDB, SemaClaw, buddyMe, PEEK, TriMem). Key refinements: formalized plan-mode as an explicit finite-state machine, adopted Sprint Contract output schema, added quality-gated Vespa indexing, and multi-granularity persistence.
>
> **Contradiction note:** This v2 was verified against the _actual text_ of all six papers (not just abstracts or traceability matrices). Four misattributions were identified and corrected below. See [Paper Verification](#paper-verification-and-references) for the corrected traceability.

## Goal

Add a `/plan` mode to the harness for read-only project exploration and research. Plan mode must not write files to the project workspace, but it may write to the blackboard and should embed the resulting plan into Vespa so future agents and processes can retrieve it semantically.

## Core Semantics

- `/plan <question>` runs a one-shot planning request.
- `/plan` without arguments enters **sticky plan mode**.
- `/plan on` / `/plan off` — explicit mode toggles.
- `/chat` exits sticky plan mode and returns to normal chat.
- Plan mode produces **plans, findings, risks, assumptions, and open questions**.
- Plan mode does not implement changes or modify project files.
- Plan mode should strongly prefer `search_documents` for project docs, specs, plans, papers, and prior indexed plans before using code/file search.
- Plan mode outputs follow a **Sprint Contract schema** (informed by buddyMe §4) to ensure plan artifacts are actionable by downstream agents.

## Mode FSM

Plan/chat mode switching is modeled as a session-scoped finite-state machine with two states:

```
                  /plan
  ┌─────────┐  ──────────►  ┌──────────┐
  │  CHAT   │               │  PLAN    │
  │ (normal)│  ◄──────────  │ (sticky) │
  └─────────┘    /chat      └──────────┘
       │                          │
       │  /plan <q>               │  /plan off
       │  (one-shot)              │  or /chat
       ▼                          ▼
  [Plan response           [Exit plan mode,
   appended to              return to CHAT]
   plan_messages]
```

**Intent-stage binding** (pattern inspired by SDOF's Λ formulation — intent constraints orthogonal to transition validation):

| Mode   | Allowed Intents                                    | Blocked Intents                                      |
| ------ | -------------------------------------------------- | ---------------------------------------------------- |
| `CHAT` | `read`, `write`, `execute`, `edit`, `deploy`       | (none — full access)                                 |
| `PLAN` | `read`, `research`, `search`, `plan`, `index-plan` | `write`, `edit`, `execute`, `deploy`, `skill-manage` |

The runtime **must enforce** these at the dispatcher level, not just the prompt. A tool call with a write intent received while in `PLAN` mode results in an immediate rejection with a typed `reject` signal (per SDB §2.3 — the verifier component of the stochastic-deterministic boundary).

**Important distinction from SDOF:** SDOF's FSM (GoalStage) governs persistent cross-session enterprise workflow legality (e.g., screening → interview → offer in recruitment). Our FSM is a session-scoped interaction mode toggle. The shared pattern is the _intent-stage binding formulation_ (Λ) — an orthogonal constraint layer on top of transition validation — not the FSM structure itself. See [Paper Verification](#paper-verification-and-references).

## Permission Boundary

Plan mode enforces the no-project-write rule at the **runtime/tool layer** (structural enforcement, per SemaClaw §3.3.4 — "constraints imposed structurally are more reliable than constraints imposed through convention").

### Tier-1: Infrastructure Tools (pre-authorized, always available)

These are runtime-internal tools with no side effects outside the agent's own scope:

- `search_documents` — read-only semantic retrieval from Vespa
- `read_memory` — blackboard reads only
- `skills_list` — metadata listing, no execution
- `skill_view` — read-only skill content retrieval

### Tier-2: Read-Only External Tools (allowlisted)

These can read project files but cannot modify them:

- `read_file`
- `search_files`

### Blocked (all write-capable tools)

- `write_file`
- `patch`
- `skill_manage`
- `execute_python`
- `container_spawn` / `container_exec`
- `index_documents` (modifies the Vespa index — write)
- `context-map-materializer` (modifies context map — write)
- `observe` (writes to context map blackboard — see Open Questions for restricted-mode variant)
- direct project skill execution that can write the workspace
- workflows, pipelines, and autonomous goal loops unless explicitly run outside plan mode

**Blackboard writes for plan persistence and Vespa feeds are allowed** — these are infrastructure operations scoped to the plan session, not project mutations. `search_documents` keeps its current `blackboard: read_write` permission for retrieval/context-map event recording.

## Runtime Design

### Two runtimes

```python
plan_runtime: PydanticAgentRuntime
plan_messages: list[ModelMessage]
```

Build alongside the normal chat runtime in `build_app_state()`, using the normal SOUL, state context, context map, and skill catalog plus the plan-mode prompt overlay.

### Runtime builder with tiered allowlists

```python
infra_tools = {
    "search_documents",
    "read_memory",
    "skills_list",
    "skill_view",
}

readonly_external_tools = {
    "read_file",
    "search_files",
}
```

Use allowlists (not blocklists) so newly added write-capable tools are never accidentally exposed in plan mode.

## Plan Output Schema — Sprint Contract (inspired by buddyMe §4)

Plan mode output follows a structured schema so downstream agents can reliably parse and execute it. The schema is based on buddyMe's Sprint Contract format, but **note**: buddyMe generates this schema through a multi-round adversarial Generator-Evaluator discussion (95% converge in 2-3 rounds, §4.1). In v2, a single LLM pass produces it. The full adversarial loop is tracked as a future enhancement (see Future Work).

```json
{
  "plan_id": "<uuid>",
  "session_id": "<session>",
  "created_at": "<iso8601>",
  "query": "<original user request>",

  "requirement_summary": "One-paragraph restatement of what was asked.",
  "key_deliverables": [
    { "id": "D1", "description": "What must be produced", "success_criterion": "Measurable condition" }
  ],

  "technical_approach": "Markdown description of how to achieve the deliverables.",

  "task_plan": [
    {
      "task_id": "T1",
      "label": "SEARCH",
      "description": "Find existing implementation of X",
      "depends_on": [],
      "evidence": ["docs/papers/2605.15204.pdf §3.1", "src/harness_poc/core/dispatcher.py:42-58"]
    },
    {
      "task_id": "T2",
      "label": "CREATE",
      "description": "Implement Y in src/...",
      "depends_on": ["T1"],
      "evidence": []
    }
  ],

  "risks": [{ "risk": "Naming collision with existing module Z", "likelihood": "low", "impact": "medium" }],

  "assumptions": ["The Vespa document client accepts direct text input without a backing file."],

  "open_questions": ["Should observe() be unblocked in plan mode for context-map entries?"],

  "confidence_score": 0.85,
  "evidence_citations": [
    "SDOF (2605.15204) §3.2 — intent-stage binding formulation",
    "SemaClaw (2604.11548) §3.3.4 — structural enforcement"
  ]
}
```

**Task labels** (from buddyMe Sprint Contract): `SEARCH`, `CREATE`, `EDIT`, `VERIFY`, `RESEARCH`. These enable downstream agents to quickly assess which tasks require file system access vs. read-only research.

## Quality Gate (Vespa Indexing Filter)

Not every `/plan` response is worth embedding. Apply a **deterministic quality gate** before feeding into Vespa. This gate is an instance of the SDB verifier pattern (§2.3 of SDB paper): all checks operate on already-parsed structured data with zero additional LLM calls.

### Gate Criteria

A plan passes the gate if it meets ALL of:

1. **Structured output valid** — JSON conforms to Sprint Contract schema above. (Deterministic: JSON schema validator.)
2. **Contains ≥2 risks OR ≥2 assumptions** — indicates substantive analysis, not a trivial response. (Deterministic: count fields.)
3. **Contains ≥1 evidence citation** — demonstrates research grounding. (Deterministic: count array length.)
4. **Confidence score ≥ 0.5** — avoids indexing low-confidence guesses. (Deterministic: numeric comparison.)

Plans that fail the gate are persisted to blackboard only (for the current session) but are **not fed to Vespa**.

> **Important:** These thresholds are heuristic, not derived from paper evidence. The papers do not provide empirically validated thresholds for plan quality gates. In buddyMe, the confidence-score approach uses numerical thresholds (0.0-1.0) for the _Evaluator's assessment of plan quality after adversarial review_ — a different context with a different distribution. Our thresholds should be tuned after collecting real usage data. See Future Work.

### Indexing Path

```python
DocumentIndexer.index_text(
    uri=f"blackboard://plans/{session_id}/{plan_id}",
    title=f"Plan: {truncated_query}",
    kind="plan",
    text=plan_text,                      # full Sprint Contract JSON as text
    metadata={
        "session_id": session_id,
        "plan_id": plan_id,
        "query": user_query,
        "source": "plan_mode",
        "confidence": confidence_score,
        "task_labels": ["SEARCH", "CREATE"],
        "deliverable_count": len(deliverables),
        "passed_quality_gate": True,
    },
    force=True,
)
```

Reuse existing retrieval primitives:

- `make_document_chunks(...)`
- `compute_content_hash(...)`
- `make_source_id(...)`
- `LiveVespaDocumentClient.feed_chunks(...)`
- document source/chunk metadata tables

## Multi-Granularity Persistence (architectural pattern inspired by TriMem)

Store plans at three granularities.

**Domain note:** TriMem (2605.19952) designs three granularities for _agent conversation memory_ (verbatim dialogues → extracted facts → synthesized profiles). The pattern transfers conceptually — multiple granularities serve different access patterns — but TriMem's specific mechanisms (TextGrad prompt optimization, source dialogue identifiers for conversation segments, entity profile construction) do not apply to document indexing. The mapping below is architectural inspiration, not operational adoption.

| Layer                    | Storage                     | Format                    | Purpose                                 |
| ------------------------ | --------------------------- | ------------------------- | --------------------------------------- |
| **Verbatim**             | Vespa (text chunks)         | Full Sprint Contract JSON | Semantic retrieval by future agents     |
| **Atomic facts**         | Blackboard `plan:{plan_id}` | Structured metadata dict  | Fast lookup by plan_id, session listing |
| **Synthesized** (future) | Vespa `kind="plan-profile"` | Cross-plan consolidation  | Aggregated knowledge across sessions    |

### Blackboard Payload (atomic facts)

```json
{
  "plan_id": "<id>",
  "session_id": "<session>",
  "query": "<original user request>",
  "content": "<final plan Sprint Contract JSON>",
  "vespa_uri": "blackboard://plans/<session>/<id>",
  "kind": "plan",
  "confidence": 0.85,
  "passed_quality_gate": true,
  "task_labels": ["SEARCH", "CREATE"],
  "deliverable_count": 3,
  "created_at": "<iso8601>"
}
```

## Plan Mode Prompt

Create `harness_poc/system_prompts/PLAN_MODE.md` and append it to the plan runtime system prompt.

The prompt should state:

- You are in **read-only planning mode** (FSM state: `PLAN`).
- Do not write or modify project files.
- Do not create, patch, or delete skills.
- Do not run implementation workflows, pipelines, or autonomous goals.
- Use `search_documents` early when the answer might live in indexed docs, specs, plans, papers, or prior plans.
- Use code/file search only when exact current code behavior is needed.
- **Output must conform to the Sprint Contract schema** (structured JSON with deliverables, task plan, risks, assumptions, confidence score, evidence citations).
- Use the following task labels: `SEARCH` (find existing code/docs), `CREATE` (new implementation), `EDIT` (modify existing), `VERIFY` (test/validate), `RESEARCH` (investigate without code change).
- Include evidence citations referencing specific files, line numbers, paper sections, or prior plans.
- Assign a confidence score (0.0–1.0) reflecting how certain you are that the plan is correct.
- Plans with confidence < 0.5 or fewer than 2 risks/assumptions will not be indexed into Vespa.

## REPL And TUI Wiring

In `harness_poc/repl.py`:

- Add `/plan` command detection before `/goal` and direct resource dispatch.
- Add `handle_plan_command(...)` — routes to `plan_runtime`.
- Add `handle_plan_input(...)` for sticky mode.
- Reuse the existing streaming callbacks.
- Track plan responses in `plan_messages`, not `pydantic_messages`.
- Log mode transitions as structured events.

In `harness_poc/repl_completion.py`:

- Add `/plan`, `/plan on`, `/plan off`, and `/chat` to root completions.

In the TUI:

- Show a small mode indicator (e.g., `[PLAN]` or `[CHAT]`) when sticky plan mode is active.
- Keep output rendering the same as chat output.

## Tests

### Unit tests

- `/plan <text>` routes to `plan_runtime`, not `pydantic_runtime`.
- Plan history is stored in `plan_messages`, not `pydantic_messages`.
- Plan runtime exposes tier-1 and tier-2 allowed tools.
- Plan runtime rejects `write_file`, `patch`, `skill_manage`, `execute_python`, `container_spawn`.
- Mode transition events are logged correctly.
- Plan output is validated against Sprint Contract schema before persistence.

### Quality gate tests

- A plan with 0 risks and 0 assumptions is **not** fed to Vespa (written to blackboard only).
- A plan with confidence 0.3 is **not** fed to Vespa.
- A plan with 3 risks and confidence 0.9 **is** fed to Vespa with `kind="plan"`.
- Plans that fail the gate still appear in `plan_messages` and blackboard.
- The quality gate consumes zero additional LLM calls (verified by mock).

### Integration tests

- Completed plans are written to blackboard with correct payload structure.
- Completed plans (passing quality gate) are fed into Vespa with `kind="plan"`.
- `/plan` and `/chat` appear in completions.
- `/plan` then `/chat` then `/plan` cycles correctly through FSM states.

## Acceptance Criteria

1. A user can ask `/plan <question>` and get a research-grounded, structured Sprint Contract plan.
2. The plan mode agent cannot write project files through exposed tools (verified by integration test).
3. The plan mode agent can write plan metadata/content to blackboard.
4. Plans that pass the quality gate are embedded into Vespa without creating a project file.
5. Plans that fail the quality gate persist only in blackboard (not in Vespa).
6. Another agent or process can retrieve indexed plans semantically through `search_documents` with `kind="plan"`.
7. Mode transitions (`/plan` → `/chat` → `/plan`) are clean and auditable.
8. Existing normal chat, skill execution, workflows, pipelines, and goal mode continue to behave unchanged.

## Paper Verification and References

The v2 design was cross-referenced against the _actual text_ of all six papers (not just abstracts or auto-generated summaries). Below is the corrected traceability matrix with known limitations acknowledged.

| Concept                                                    | Source                                              | How v2 Uses It                                                                         | Limitation / Caveat                                                                                                                                                                                                                                                                                                          |
| ---------------------------------------------------------- | --------------------------------------------------- | -------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Intent-stage binding (Λ) — orthogonal constraint layer** | SDOF (2605.15204) §3.1                              | Plan mode's allowed/blocked intents per FSM state                                      | SDOF's Λ is for enterprise process legality (recruitment workflows). Our FSM is a session-scoped mode toggle. The _formulation_ (intent constraints orthogonal to transitions) transfers; the _domain_ does not.                                                                                                             |
| **Stochastic-deterministic boundary (SDB)**                | SDB (2605.20173) §2.3                               | Tool allowlists = deterministic verifier; rejected calls return typed `reject` signals | Clean mapping. No caveat.                                                                                                                                                                                                                                                                                                    |
| **Architectural momentum (µ)**                             | SDB §5.1                                            | Structural enforcement (allowlists) dominates per-call model quality for reliability   | Clean mapping. The µt + σξ(t) model supports the design priority.                                                                                                                                                                                                                                                            |
| **Structural > conventional constraints**                  | SemaClaw (2604.11548) §3.3.4                        | No-project-write enforced at runtime, not prompt                                       | Clean mapping.                                                                                                                                                                                                                                                                                                               |
| **Two-tier permission policy**                             | SemaClaw §3.3.2                                     | Infrastructure tools (pre-authorized) vs. read-only external tools (allowlisted)       | Clean mapping. SemaClaw's distinction is internal vs. external MCP servers; ours is infra vs. read-only. The tiering pattern transfers.                                                                                                                                                                                      |
| **Sprint Contract output schema**                          | buddyMe (2605.16821) §4.1                           | Structured output with deliverables, tagged task labels, success criteria              | buddyMe generates this via _multi-round adversarial Generator-Evaluator discussion_ (95% converge in 2-3 rounds). Our v2 uses a single LLM pass. The schema's benefits (20% requirement-omission capture) were demonstrated _with_ adversarial review and may not transfer to single-pass generation.                        |
| **Numerical thresholds > boolean gates**                   | buddyMe §8                                          | Confidence score (0.0–1.0) used instead of binary "plan valid?"                        | buddyMe's thresholds apply to the Evaluator's assessment of adversarial-review output — a different distribution than single-pass plan generation. Our thresholds (≥0.5, ≥2 risks) are heuristic, not empirically validated.                                                                                                 |
| **Quality gate (deterministic filter)**                    | SDB §2.3 (verifier), **not** PEEK                   | Deterministic checks on structured output before Vespa feed                            | Originally attributed to PEEK's Distiller in v2 draft; corrected after paper verification. The quality gate is an SDB verifier, not a PEEK materializer. PEEK's Distiller is an LLM call that produces orientation knowledge from execution trajectories — structurally different.                                           |
| **Multi-granularity persistence**                          | TriMem (2605.19952) §3 — architectural pattern only | Verbatim (Vespa) + atomic facts (blackboard) + synthesized profiles (future)           | TriMem's three granularities are designed for _agent conversation memory_ (dialogue → facts → profiles). Our domain is _document indexing_ (plan text → metadata → cross-plan synthesis). The three-granularity _pattern_ transfers; TriMem's mechanisms (TextGrad prompt optimization, source dialogue identifiers) do not. |

### Papers that were checked but not directly used

- **PEEK (2605.19932):** Context map for agent orientation caching. The Distiller → Cartographer → Evictor pipeline does not apply to plan indexing. PEEK's domain is per-query agent-side caching; ours is session-scoped plan persistence. No contradiction — just different problems.
- **TriMem's TextGrad component:** Out of scope. TriMem uses TextGrad for lifelong prompt evolution in conversation memory. Plan mode doesn't need prompt evolution across sessions.

## Known Contradictions and Unresolved Tensions

### Tension 1: Single-pass generation vs. adversarial review

buddyMe's Sprint Contract was designed and validated with adversarial Generator-Evaluator discussion. Our v2 uses single-pass generation. The 20% requirement-omission capture rate (§6.1 of buddyMe) is a result of the adversarial mechanism, not the structured output format. If we want that benefit, we need to either:

- **A (v2):** Accept that our quality benefits are limited to what a single LLM pass can provide (format consistency, parseability), and attribute appropriately.
- **B (future):** Implement the full Evaluator-Defender loop (2-3 rounds, configurable) for high-stakes plans.

Recommendation: **A for v2, B as a configurable option post-v2.**

### Tension 2: Quality gate thresholds are heuristic

The thresholds (≥2 risks, ≥1 evidence, confidence ≥ 0.5) have no paper basis. No paper provides empirically validated thresholds for plan-quality gates. These should be flagged as **initial tuning values** and revisited after collecting real usage data. Add a `plan_stats` blackboard key that accumulates gate pass/fail ratios for threshold calibration.

### Tension 3: SDOF Λ formulation is domain-shifted

SDOF's intent-stage binding is validated on enterprise recruitment workflows with 1,671 real API calls across 48 job positions (§4). Applying it to a two-state (CHAT/PLAN) mode switch is a significant domain shift. The Λ formulation is described as "orthogonal to transition graphs" (§3.1), which means it should generalize — but this is a claim about the formulation, not an empirical result on mode-switching.

## Future Work (beyond v2)

1. **Adversarial Sprint Contract generation** — full buddyMe-style Generator-Evaluator loop for high-stakes plans.
2. **Threshold calibration** — collect gate pass/fail statistics and tune confidence/risk thresholds empirically.
3. **Cross-plan synthesis profiles** — TriMem-inspired consolidation of related plans into profile entries.
4. **Multi-turn plan deliberation** — allow `/plan` to extend an existing plan with follow-up research.
5. **Vespa eviction for plans** — TTL-based sweep if plan corpus grows beyond useful bounds.

## Open Questions (for team discussion)

1. **`observe()` in plan mode?** — The tool writes to the context map. If plan-mode discoveries should be persistable as observations, we need a mode-aware variant that tags observations with `source: plan_mode`. Currently blocked.
2. **Schema versioning?** — The Sprint Contract JSON schema is not versioned. Consider adding a `schema_version` field now to allow evolution.
3. **Single-pass vs. adversarial trade-off?** — Is the latency/cost of adversarial review justified for the plan use case, or is single-pass sufficient given plans are not production code?
