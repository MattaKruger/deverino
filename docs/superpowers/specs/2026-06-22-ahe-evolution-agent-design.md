# AHE Evolution Agent — Design Spec

**Date:** 2026-06-22
**Status:** Draft — ready for implementation planning
**Author:** Session 2026-06-22 (SAGE/AHE exploration)
**Handoff:** This spec is self-contained. Read this + the referenced files to begin implementation. The conversation that produced this spec is not available; all necessary context is encoded here.

---

## 1. Summary

Design an **AHE Evolution Agent** for the Deverino harness — a meta-level agent that uses deep telemetry to propose, evaluate, and promote revisions to harness components. This extends Deverino's existing deterministic calibration mechanism into an agent-driven five-stage optimization loop with governed mutation.

The design is grounded in:

- **AHE (Agentic Harness Engineering)** from the Code as Agent Harness survey (arXiv:2605.18747, §3.5)
- **SAGE** (arXiv:2409.00872) — self-evolving agents with reflective + memory-augmented abilities
- **Deverino's existing context map** — which already implements SAGE's MemorySyntax primitives (eviction, distillation, calibration)

---

## 2. Background

### 2.1 AHE — Agentic Harness Engineering

From the Code as Agent Harness paper (§3.5), AHE names a harness-level design problem: how to measure and revise the software substrate that turns an LLM into a coding agent. It is distinct from prompt engineering (changes instructions) and context engineering (changes evidence presented). AHE treats the **operating environment** as the object of analysis.

**Harness substrate components (the revision surface):** tool schemas, planning artifacts, memory policies, retrieval strategies, sandbox configuration, verification sensors, permission tiers, routing rules, multi-agent workflows, human-review gates.

**The AHE Evolution Agent (§3.5.2):** A meta-level agent that uses deep telemetry to propose, evaluate, and promote revisions to harness components. Unlike a task agent (edits the target repo), the Evolution Agent **edits the operating conditions** under which later task agents work.

- Input: corpus of trajectories (telemetry)
- Output: revised prompt template, retrieval policy, tighter tool schema, added validator, changed permission rule, workflow-topology adjustment, new regression test

**Five-stage loop:**

1. Observe — collect telemetry from PEV executions
2. Diagnose — attribute cost, latency, invalid actions, test failures, permission denials to specific harness components
3. Propose — candidate revisions
4. Evaluate — run revised harness on held-out tasks / replayed traces
5. Promote — only changes that improve reliability, cost, or safety without regressing previously solved cases

**Governed Harness Mutation (§3.5.3):** Not unconstrained self-modification. Candidate changes evaluated in sandboxes, compared against regression suites, recorded with auditable rationales. HITL approval required for: permission boundaries, network access, credential handling, deployment behavior, human-review requirements. The Evolution Agent is itself subject to the PEV loop.

**Three strands in the literature:**

- AutoHarness [14] — automatic synthesis of code harnesses
- Meta-Harness [13] — harness design as optimization over model-facing infrastructure
- Observability-driven AHE [281] — telemetry-rich diagnosis of where the agent loop fails

### 2.2 SAGE — Self-evolving Agents

From SAGE (arXiv:2409.00872, Neurocomputing 2025):

**Architecture:** Three agents (User → Assistant → Checker). Assistant loop: observation → action → reflection → output.

**Three core mechanisms:**

1. Iterative feedback — Checker provides feedback, Assistant updates policy
2. Reflection — `rt = ref(o1:t, R1:t)` stored in long-term memory
3. MemorySyntax — Ebbinghaus forgetting curve + linguistic optimization
   - Retention: `R(It, τ) = e^(-τ/S)` where S = information strength
   - Three-tier routing: R ≥ θ1 → STM, θ2 ≤ R < θ1 → LTM, R < θ2 → discard
   - Information-theoretic grounding: `S(It) = H(It)/f(t)` (entropy / forgetting function)

### 2.3 The SAGE ↔ AHE Connection

Both involve self-improvement through feedback loops, but at different layers:

- **AHE** = meta-level: a separate Evolution Agent revises the harness for other task agents. Top-down.
- **SAGE** = self-level: the agent evolves its own memory and strategies. Bottom-up.

In the code-as-harness framing, SAGE's memory policy IS a harness component. SAGE's reflection loop IS a PEV-like control process. SAGE is an instance of AHE principles applied at the agent level.

### 2.4 Key Finding: Deverino's Context Map Already Implements MemorySyntax

This is the critical finding from the exploration session. Deverino's context map package (`harness_poc/core/context_map/`) already has SAGE's MemorySyntax primitives:

| SAGE MemorySyntax                     | Deverino context map                                           |
| ------------------------------------- | -------------------------------------------------------------- |
| Forgetting (discard below threshold)  | Eviction (`MapEntryEvicted` events)                            |
| Linguistic optimization (compression) | Distiller (`run_distiller`, `DistilledBatch`)                  |
| Strength-based ranking (`S = H/f(t)`) | Calibration (`priority_weights` from reference/eviction rates) |
| STM/LTM routing                       | Context map materialization (blackboard → working context)     |
| Information categories                | `ObservationType`, `Tag`, `SECTION_MAP`                        |

The context map IS MemorySyntax, implemented as a deterministic cartographer. The calibration mechanism — tuning priority weights from observed reference and eviction events — is strength-based ranking driven by telemetry, not by the Ebbinghaus curve.

### 2.5 Memory Tier Reframing (Clean Mapping)

The STM/LTM mapping fits cleanly when applied at the **subagent level**:

```
LTM = blackboard (PostgreSQL, durable, shared, cross-session)
STM = subagent working memory (ephemeral, per-task)
Context map = the bridge (materializes relevant LTM → working context, persona-lensed)
```

A subagent gets: a persona-lensed view of the blackboard (via context map) + its own ephemeral STM during the task + results written back to the blackboard (LTM) on completion.

---

## 3. Existing Deverino Components

### 3.1 Context Map Package

**Location:** `harness_poc/core/context_map/`

**Modules:**

- `cartographer.py` — `deterministic_cartographer` (materializes context map from blackboard)
- `distiller.py` — `run_distiller` (compresses/distills entries)
- `calibrate.py` — `run_calibration` (tunes priority_weights from event log)
- `render.py` — `render_context_map` (renders to prompt block)
- `schema.py` — `MapEntry`, `EvictionRecord`, `ObservationType`, `Tag`, `DistilledBatch`, `DistillerEntry`, `CartographerResult`
- `sections.py` — `SECTION_MAP`, `assign_section`
- `copt_gate.py` — `embed_single`, `embed_summaries`
- `format.py` — `format_context_window`, `format_persona_lens`, `format_verified_state`, `format_working_context`
- `config.py` — `CartographerConfig`, `DistillerConfig`

**Design spec:** `docs/superpowers/specs/2026-05-23-deterministic-cartographer-design.md` (verify this path exists — may be in a different location)

**System prompt injection:** `app_factory.py:509-516` — context map rendered as `sys.context_map` binding, injected when `config.cartographer.prompt_block != "none"`.

### 3.2 Event System (Telemetry Source)

**Location:** `harness_poc/core/events/`

**Relevant events (from `events.py`):**

- `MapEntryReferenced` — context map entry was used
- `MapEntryEvicted` — context map entry was evicted
- `MapEntryInserted` — context map entry was added
- `ContextWarmed` — context was warmed (e.g., by v2_probe)
- `DelegateTaskCompleted` — subagent finished (has `task_id`, `output_label`, `summary`)
- `GateCompleted` / `GateFailed` — v2 gate results
- `AgentTurnRecorded` — agent turn telemetry
- `ExecutionCompleted` — execution finished
- `SpecCommitted` — spec was committed

**Event store:** `EventStore` in `harness_poc/core/events/`

This IS the deep telemetry substrate that AHE §3.5.1 describes. The event log contains trajectory-level signals: what was referenced, what was evicted, what failed, what completed.

### 3.3 Calibration Mechanism (Existing AHE Primitive)

**Location:** `harness_poc/core/context_map/calibrate.py`
**CLI:** `harness-poc cartographer calibrate` (in `cli.py:1256-1266`)

**What it does:**

- Reads `MapEntryReferenced`, `MapEntryEvicted`, and `MapEntryInserted` events from the event log
- Computes target `priority_weights` using a deterministic multiplicative formula
- `--dry-run` prints current, target, and delta per `ObservationType`
- `--apply` writes new weights to `harness.yaml`

**This is stages 1-3 of the AHE loop (observe → diagnose → propose) for a single component (priority_weights).** It's deterministic, not agent-driven. The Evolution Agent generalizes this.

### 3.4 v2 System (PEV Loop)

**CLI commands (in `cli.py`):**

- `v2_probe` (L1339-1343) — sandbox probe, extracts constraints, warms context map. "Step #1."
- `v2_gate` (L1355-1359) — deterministic review gate, runs test suite, updates context map to verified state. "Step #3."
- `v2_context` (L1387-1402) — materialize context map through persona+pedagogy lens.

This is a PEV (Plan-Execute-Verify) loop. The v2 system is the robust replacement for `consolidate_state`.

### 3.5 Blackboard

**Location:** `harness_poc/core/storage/database.py` (`BlackboardDatabase`)
**Proxy:** `harness_poc/core/storage/blackboard_proxy.py` (classifies read vs write operations)

**Key methods:** `read_memory`, `get_context_map`, `get_context_maps`, `get_cycle`

**Delegate results stored as:** `delegated:{task_id}` keys

### 3.6 Delegate Task (Subagent System)

**Location:** `harness_poc/system_skills/delegate_task/skill.py`

**Interface:**

- Input: `persona` (required), `objective` (required), `template_name` (optional)
- Output: `DelegatedTaskOutput` — `status` (completed/failed/blocked), `summary`, `artifacts`
- Writes result to blackboard as `delegated:{task_id}`
- Publishes `DelegateTaskCompleted` event

**Currently no STM tier** — subagents run, write to LTM (blackboard), return. The gap: subagents don't have dedicated working memory during execution.

### 3.7 Consolidate State (To Be Replaced)

**Location:** `harness_poc/system_skills/consolidate_state/skill.py`

**What it does:** Consolidates session state (notes, decisions, next_actions, open_questions) into durable project state. Three modes: preview → propose → approve.

**Status:** The developer does not use this skill. It was the first skill introduced. The v2 system (probe/gate/context) is the emerging replacement. This spec does not design the consolidation replacement, but the AHE Evolution Agent should be designed to coexist with the v2 system.

---

## 4. The Gap

Deverino already has:

- ✅ Deep telemetry (event system with trajectory-level signals)
- ✅ A revision surface (context map: priority_weights, eviction policy, distillation rules)
- ✅ A deterministic optimization loop (calibrate: observe → diagnose → propose for priority_weights)
- ✅ A PEV loop for task execution (v2: probe → gate → context)
- ✅ Memory management primitives (eviction, distillation, calibration)

What's missing for full AHE:

- ❌ An **Evolution Agent** — an agent-driven (not deterministic) meta-level optimizer
- ❌ The **full five-stage loop** — calibrate does observe+diagnose+propose but skips agent-driven proposal and held-out evaluation
- ❌ **Governed mutation** — HITL gates for risky harness changes, auditable rationales
- ❌ **Evaluation** — running proposed changes against held-out tasks / replayed traces
- ❌ **Promotion discipline** — only promoting changes that improve without regressing
- ❌ **Isolated AHE memory** — dedicated blackboard namespace for proposals, evaluations, promotions

---

## 5. Design: AHE Evolution Agent

### 5.1 Definition

The AHE Evolution Agent is a meta-level agent that optimizes the Deverino harness by proposing, evaluating, and promoting revisions to harness components. It is NOT a task agent — it does not edit code or produce task output. It edits the **operating conditions** under which task agents and subagents work.

**Architectural role:** The Evolution Agent sits above the task-execution layer. It observes telemetry from task executions (including subagent delegations and v2 gate runs), diagnoses harness-level problems, proposes revisions, evaluates them in isolation, and promotes verified improvements.

### 5.2 The Five-Stage Loop (Mapped to Deverino)

```
┌─────────────────────────────────────────────────────────────┐
│                    AHE EVOLUTION AGENT                       │
│                                                              │
│  1. OBSERVE     2. DIAGNOSE    3. PROPOSE                   │
│  ─────────      ──────────     ─────────                    │
│  Query event    Attribute      Agent generates               │
│  log for        failures/cost  candidate revisions           │
│  telemetry      to harness     (beyond deterministic         │
│  signals        components     calibration)                  │
│                                                              │
│  4. EVALUATE    5. PROMOTE                                   │
│  ─────────      ─────────                                    │
│  Run proposed   If eval passes +                             │
│  change against  governance allows:                          │
│  held-out tasks  apply change                                │
│  / replayed      If HITL required:                           │
│  traces via      surface to user                             │
│  v2 probe/gate                                                │
│                                                              │
│  Telemetry: event system (MapEntry*, Delegate*, Gate*)       │
│  Memory: blackboard (ahe:* namespace)                        │
│  Revision surface: context map config, distiller rules,      │
│    eviction thresholds, permission tiers, tool schemas       │
└─────────────────────────────────────────────────────────────┘
```

**Stage 1: Observe**

Query the event store for trajectory-level signals. Aggregate into a telemetry summary. Key queries:

- Reference/eviction rates per `ObservationType` and section (from `MapEntryReferenced`, `MapEntryEvicted`)
- Delegate task success/failure rates (from `DelegateTaskCompleted` — `status` field)
- Gate pass/fail rates (from `GateCompleted`, `GateFailed`)
- Context warm events (from `ContextWarmed`)
- Token/cost/latency if available (from `AgentTurnRecorded`, `ExecutionCompleted`)

Output: a structured telemetry summary stored as `ahe:telemetry:{cycle}` in the blackboard.

**Stage 2: Diagnose**

Attribute observed problems to specific harness components. The agent (LLM) receives the telemetry summary and identifies:

- High eviction + low reference → distillation policy too aggressive, or section priorities misaligned
- Repeated `DelegateTaskCompleted` with `status=failed` → tool schema issue, permission boundary too tight, or persona prompt inadequate
- `GateFailed` clustering on specific task types → verification sensors too strict or too loose
- Context warming not helping (ContextWarmed but subsequent tasks still fail) → retrieval strategy gap

Output: a diagnosis stored as `ahe:diagnosis:{cycle}` — list of `(observed_problem, attributed_component, evidence)` tuples.

**Stage 3: Propose**

Generate candidate revisions. The agent proposes specific, actionable changes:

- Adjust `priority_weights` for specific `ObservationType` values (extends what `calibrate` computes deterministically)
- Change eviction thresholds (θ1, θ2 in SAGE's terms — mapped to context map config)
- Modify distillation rules (what gets compressed, when)
- Adjust permission tiers (read-only → sandbox-edit → full-access mappings)
- Revise tool schemas (tighten descriptions, add constraints)
- Insert HITL gates at new decision points

Each proposal includes:

- `target_component` — which harness component
- `observed_problem` — what telemetry signal triggered it (link to diagnosis)
- `proposed_change` — the specific revision (as a config diff or rule update)
- `governance_tier` — auto-promote vs HITL-required (see §5.5)
- `rationale` — auditable explanation

Output: proposals stored as `ahe:proposal:{proposal_id}` in the blackboard.

**Stage 4: Evaluate**

Run the proposed change against held-out tasks or replayed traces. Use the v2 system:

- `v2_probe` — sandbox the proposed change, fail-fast
- `v2_gate` — run test suite / regression suite against the revised harness config
- Compare against baseline (current config) on the same task set

Evaluation criteria:

- Does it improve the diagnosed problem? (eviction rate down, success rate up, etc.)
- Does it regress previously passing cases? (regression suite)
- Does it stay within cost/latency budgets?

Output: evaluation result stored as `ahe:evaluation:{proposal_id}` — pass/fail, metrics, regression status.

**Stage 5: Promote**

If evaluation passes:

- **Auto-promote** (governance_tier = auto): apply the change to `harness.yaml` / context map config. Record promotion.
- **HITL-required** (governance_tier = hitl): surface the proposal + evaluation to the user. Wait for approval. Apply if approved.

Promotions are recorded as `ahe:promotion:{proposal_id}` with: applied change, timestamp, approval status, rationale.

### 5.3 Data Model (Blackboard Namespace)

All AHE artifacts stored in the blackboard under the `ahe:` prefix:

| Key pattern                    | Content                                       | Lifecycle                |
| ------------------------------ | --------------------------------------------- | ------------------------ |
| `ahe:telemetry:{cycle}`        | Aggregated telemetry summary for cycle N      | Written in stage 1       |
| `ahe:diagnosis:{cycle}`        | Diagnosis with attributed components          | Written in stage 2       |
| `ahe:proposal:{proposal_id}`   | Candidate revision with rationale             | Written in stage 3       |
| `ahe:evaluation:{proposal_id}` | Eval result (pass/fail, metrics, regressions) | Written in stage 4       |
| `ahe:promotion:{proposal_id}`  | Applied change record with approval           | Written in stage 5       |
| `ahe:regression_suite`         | Canonical task set for evaluation             | Maintained across cycles |

`{cycle}` corresponds to the context map cycle number (`db.get_cycle(corpus_key)`).

`{proposal_id}` is a unique identifier (e.g., `cycle-N-{seq}` or a UUID).

### 5.4 Telemetry Sources

The event system (`harness_poc/core/events/`) provides the deep telemetry. Events are stored across two tables:

- **`DbContextMapEvent`** (table: `context_map_events`) — context map signals, keyed by `corpus_key`. Payload is `Text` (JSON string).
- **`DbStateEvent`** (table: `state_events`) — task-level signals, keyed by `scope_id` (session_id). Payload is `JSONB` (dict).

The Evolution Agent queries both:

| Event                   | Table             | Signal                 | Diagnosis use                               |
| ----------------------- | ----------------- | ---------------------- | ------------------------------------------- |
| `MapEntryReferenced`    | `DbContextMapEvent` | Entry was useful       | Reference rate per section/type             |
| `MapEntryEvicted`       | `DbContextMapEvent` | Entry was discarded    | Eviction rate, potential over-eviction      |
| `MapEntryInserted`      | `DbContextMapEvent` | Entry was added        | Growth rate, insertion patterns             |
| `ContextWarmed`         | `DbStateEvent`    | Context was pre-warmed | Warming effectiveness                       |
| `SubAgentDispatched`    | `DbStateEvent`    | Subagent dispatched    | Delegation volume, persona distribution     |
| `SubAgentCompleted`     | `DbStateEvent`    | Subagent finished      | Success/failure/cancel rate per persona     |
| `GateCompleted`         | `DbStateEvent`    | v2 gate completed      | Gate pass/fail (pipeline step runner)       |
| `GatePassed`            | `DbStateEvent`    | Execution gate passed  | Verification success rate                   |
| `GateFailed`            | `DbStateEvent`    | Execution gate failed  | Verification failure patterns               |
| `LLMActionEmitted`      | `DbStateEvent`    | LLM token usage        | Token cost per model, input/output ratio    |
| `ExecutionCompleted`    | `DbStateEvent`    | Execution finished     | Overall task completion metrics             |

**Corrections from codebase verification (2026-06-22):**

- `DelegateTaskCompleted` is deprecated (per `specs/20260613-sub-agent-system.md`). `SubAgentCompleted` carries the `status` field ("success"/"failed"/"cancelled"); `SubAgentDispatched` carries `persona`.
- `AgentTurnRecorded` has no token fields (`messages_blob`, `ordinal` only). Token data lives in `LLMActionEmitted` (`tokens_used`, `input_tokens`, `output_tokens`, `billable_tokens`).
- Three gate events exist, not two: `GateCompleted` (pipeline step runner), `GatePassed` + `GateFailed` (execution engine).

Context map events are parameterized by `corpus_key` and time window. State events are parameterized by time window only — harness-level aggregation across all sessions.

### 5.5 Governance Model (Governed Mutation)

Not all harness changes are equal. The governance model classifies proposals by risk:

**Auto-promote (low risk):**

- `priority_weights` adjustments within bounded range (±X% from calibrated baseline)
- Distillation threshold tuning (compression aggressiveness)
- Context map section ordering
- Eviction threshold adjustments that don't risk data loss (soft eviction only)

**HITL-required (high risk):**

- Permission tier changes (read-only → sandbox-edit → full-access mappings)
- Eviction policy changes that could permanently discard entries (hard eviction)
- Tool schema changes that affect security (adding/removing constraints)
- Changes to `human-review` gates (adding/removing HITL checkpoints)
- Changes to credential handling or network access rules
- Any change to the AHE Evolution Agent's own configuration (self-modification guard)

**Hard stop (never auto-promote):**

- Disabling governance itself
- Removing audit trails
- Changing the event logging that AHE depends on

The governance tier is set in stage 3 (propose) and enforced in stage 5 (promote). HITL proposals surface to the user via the existing `orchestrator_action_required: true` mechanism (per SOUL §9.1 — surface unchanged, do not summarize).

### 5.6 Relationship to Existing Components

**Calibrate (`calibrate.py`):**

- Calibrate is the deterministic version of stages 1-3 for `priority_weights` only
- The Evolution Agent uses calibrate as a **tool** — it can invoke `run_calibration` to generate a deterministic baseline proposal, then extend beyond it with agent-driven reasoning
- Calibrate remains available as a standalone CLI command for manual use

**v2 System (probe/gate/context):**

- The v2 system is the **evaluation harness** for stage 4
- `v2_probe` sandboxes the proposed change
- `v2_gate` runs the regression suite against the revised config
- `v2_context` verifies the context map still materializes correctly
- The v2 system is NOT modified by the Evolution Agent — it's the verification layer

**Delegate Task:**

- The Evolution Agent could be implemented as a specialized delegate_task with a `harness_engineer` persona
- OR as a dedicated system skill (see §6.1 — open question)
- Subagent STM (separate gap, not in this spec) would give delegated subagents working memory; the Evolution Agent is meta-level and works on the blackboard directly

**Context Map:**

- The context map is the **primary revision target** — most proposals adjust context map config (priority_weights, eviction thresholds, distillation rules)
- The context map's verified state mechanism (`format_verified_state`) is used in stage 4 to verify the materialization is still correct after a proposed change
- The Evolution Agent does NOT modify the context map directly — it proposes config changes that the cartographer applies on the next materialization cycle

**Consolidate State:**

- Not directly related — consolidate_state handles session→project state promotion
- The v2 system is the replacement for consolidate_state
- The AHE Evolution Agent is a separate concern: harness optimization, not state consolidation
- See open question §6.4

### 5.7 The Evolution Agent Is Itself Subject to PEV

Per AHE §3.5.3, the Evolution Agent is itself subject to the PEV loop:

- It PLANS a harness mutation (stage 3)
- It EXECUTES the mutation in an isolated evaluation environment (stage 4, via v2_probe sandbox)
- It VERIFIES the result through telemetry and regression tests (stage 4, via v2_gate)
- It ESCALATES risky changes to humans (stage 5, HITL)

This means the Evolution Agent cannot bypass the v2 verification system. Its proposals are treated as untrusted until verified.

---

## 6. Resolved Decisions

Decisions locked in design review (2026-06-22). Each entry preserves the options considered and records the decision with rationale.

### 6.1 Skill vs Workflow vs Agent Type

**Decision:** Option A — system skill (`ahe_evolve`) as orchestrator entry point.

The skill handles deterministic stages (1: observe, 4: evaluate, 5: promote) in code. LLM-driven stages (2: diagnose, 3: propose) delegate to a `harness_engineer` subagent via `delegate_task`. This separates orchestration from reasoning and respects the layering (SOUL → Knowledge Skills → Executable Skills → Tool Calls).

Explicit invocation only (`/skill ahe_evolve`) — never auto-fired, per SOUL §4.2 (mutating skills blocked from chat auto-invocation).

Options considered:
- **Option A: System skill** — chosen. Fits existing architecture, no new infrastructure. Skill calls delegate_task for LLM reasoning.
- **Option B: Workflow** — rejected. Stages 2-3 need LLM-driven branching, not deterministic state transitions.
- **Option C: Dedicated agent type** — rejected. Premature abstraction for a PoC.

Deliverable implication: requires a `subagents/harness_engineer.yml` persona definition alongside the skill.

### 6.2 Evaluation Method

**Decision:** Option C — hybrid, with sharpened role per layer.

- **Replay traces** = safety/consistency gate. Re-run cartographer/distiller/eviction logic against historical event sequences with revised config. Verify: materialization succeeds, no critical entries evicted, context budget respected. Deterministic, cheap. Catches degenerate configs.
- **Held-out tasks** = improvement measure. Run the regression suite against the revised config via `v2_probe` + `v2_gate`. Captures whether the agent actually performs better. Expensive, noisy.

Only proposals that pass the replay gate proceed to held-out evaluation.

Limitation acknowledged: with a small suite and LLM variance, distinguishing "config helped" from "noise" is hard. For the PoC, evaluation catches gross regressions and improvements, not statistically significant effects. Do not over-claim what evaluation proves.

### 6.3 Regression Suite

**Decision:** Minimal suite, grown as failure modes are observed.

**Storage:** Source, not blackboard. Per `AGENTS.md`, the database is "local runtime state, not source data." The regression suite is a versioned test asset — it belongs in source. Co-located with the skill as YAML task definitions (`harness_poc/system_skills/ahe_evolve/regression/`), consumed by `v2_gate` in stage 4. The blackboard stores evaluation results against the suite, not the suite definition.

**Initial suite:** one task per category — coding, search/retrieval, delegation, state read/write. Four tasks to start.

**Known-good outcomes:** structural expectations (expected status, output contains/omits X, no errors raised), not exact output match. Deterministic success criteria on non-deterministic outputs.

### 6.4 Consolidate State Coexistence

**Decision:** Separate concern. No coupling.

AHE optimizes the harness; consolidate_state replacement is state lifecycle. Orthogonal. The v2 system is the consolidate_state replacement; AHE is a new layer that uses v2 as its evaluation harness. AHE does not require consolidate_state to be replaced first, and replacing consolidate_state does not require AHE.

### 6.5 Cycle Trigger

**Decision:** Manual invocation for the PoC.

The skill defaults to dry-run behavior (stages 1-3: observe, diagnose, propose — no mutation). Explicit promotion required. This mirrors `calibrate`'s `--dry-run` / `--apply` pattern (§3.3) and operationalizes the governance model — the developer reviews proposals before any harness mutation.

Consistent with the restraint principle (SOUL §2.3): no heavyweight processes unless explicitly asked.

Terminology clarification: an evolution cycle (one run of the five-stage loop) is distinct from a context map cycle (one materialization pass via `get_cycle`). Evolution runs are not tied to context map cycles.

Future: telemetry-threshold triggering is the right design for automated runs, but must be opt-in via config, never default — same restraint principle.

### 6.6 Subagent STM

**Decision:** Out of scope for this spec. Separate spec.

AHE does not depend on subagent STM. If STM lands first, it expands AHE's revision surface — the Evolution Agent could evaluate subagent STM configuration (working memory size, mixing strategy) as part of stage 4. Noted as a future integration point, not a current dependency.

---

## 7. Phased Implementation

### Phase 1: Telemetry Aggregation (Stage 1)

- Implement telemetry queries against the event store
- Build the `ahe:telemetry:{cycle}` data model
- Create a telemetry summary (aggregated signals per §5.4)
- No agent reasoning — deterministic aggregation only

**Files to create:**

- `harness_poc/core/ahe/__init__.py`
- `harness_poc/core/ahe/telemetry.py` — event aggregation queries

### Phase 2: Diagnosis + Proposal (Stages 2-3)

- Stage 2 (diagnose): `harness_engineer` subagent receives telemetry summary, attributes problems to harness components, writes `ahe:diagnosis:{cycle}`
- Stage 3 (propose): `harness_engineer` subagent generates candidate revisions with governance tier classification, writes `ahe:proposal:{proposal_id}`
- Introduces the `ahe_evolve` skill as orchestrator entry point
- Introduces `delegate_task` with `harness_engineer` persona for LLM reasoning

**Files to create:**

- `harness_poc/core/ahe/diagnose.py` — diagnosis orchestration (delegates to subagent)
- `harness_poc/core/ahe/propose.py` — proposal generation orchestration
- `harness_poc/system_skills/ahe_evolve/skill.py` — the skill that orchestrates the loop
- `harness_poc/system_skills/ahe_evolve/SKILL.md` — skill definition
- `subagents/harness_engineer.yml` — persona definition for the evolution agent

### Phase 3: Evaluation (Stage 4)

- Implement replay-trace evaluation (safety/consistency gate — deterministic)
- Implement held-out task evaluation (improvement measure — via v2_probe + v2_gate)
- Store evaluation results as `ahe:evaluation:{proposal_id}`
- Build the regression suite as source YAML (per §6.3 — not blackboard)

**Files to create:**

- `harness_poc/core/ahe/evaluate.py` — evaluation runner
- `harness_poc/core/ahe/regression.py` — regression suite loading and execution
- `harness_poc/system_skills/ahe_evolve/regression/` — YAML task definitions (initial 4-task suite)

### Phase 4: Promotion + Governance (Stage 5)

- Implement auto-promote (apply to `harness.yaml` / context map config)
- Implement HITL gate (surface via `orchestrator_action_required: true`)
- Store promotions as `ahe:promotion:{proposal_id}`
- Add audit trail (all promotions are logged and queryable)

**Files to create:**

- `harness_poc/core/ahe/promote.py` — promotion + governance enforcement
- `harness_poc/core/ahe/audit.py` — audit trail query

### Phase 5: CLI + Integration

- CLI command: `harness-poc ahe evolve` — run the full five-stage loop
- CLI command: `harness-poc ahe proposals` — list pending proposals
- CLI command: `harness-poc ahe promote <proposal_id>` — approve HITL proposal
- Dashboard integration: show AHE proposals/evaluations/promotions

---

## 8. References

### Papers (Indexed in Vespa)

| Paper                      | arXiv      | Location                                                 | Key sections                                             |
| -------------------------- | ---------- | -------------------------------------------------------- | -------------------------------------------------------- |
| Code as Agent Harness      | 2605.18747 | `docs/papers_test/code_as_agent_harness__2605.18747.pdf` | §3.5 AHE (chunks 65-68), §3.4 PEV (chunks 58-64)         |
| SAGE: Self-evolving Agents | 2409.00872 | `docs/papers/2409.00872.pdf`                             | §3.2.2 MemorySyntax (chunks 9-10), Appendix A (chunk 27) |

**Vespa search commands to retrieve AHE content:**

```bash
uv run harness-poc documents search "Agentic Harness Engineering telemetry evolution mutation" \
  --source-id docs-papers_test-code_as_agent_harness__2605-18747-pdf --mode keyword --hits 6 2>/dev/null

uv run harness-poc documents search "MemorySyntax short-term long-term memory decay retention" \
  --source-id docs-papers-2409-00872-pdf --mode keyword --hits 5 2>/dev/null
```

### Deverino Code

| Component                      | Path                                                                                   |
| ------------------------------ | -------------------------------------------------------------------------------------- |
| Context map package            | `harness_poc/core/context_map/`                                                        |
| Context map spec               | `docs/superpowers/specs/2026-05-23-deterministic-cartographer-design.md` (verify path) |
| Calibration                    | `harness_poc/core/context_map/calibrate.py`                                            |
| Event system                   | `harness_poc/core/events/events.py`                                                    |
| Event store                    | `harness_poc/core/events/`                                                             |
| Blackboard                     | `harness_poc/core/storage/database.py`                                                 |
| Blackboard proxy               | `harness_poc/core/storage/blackboard_proxy.py`                                         |
| Delegate task                  | `harness_poc/system_skills/delegate_task/skill.py`                                     |
| Consolidate state (to replace) | `harness_poc/system_skills/consolidate_state/skill.py`                                 |
| System prompt composition      | `harness_poc/app_factory.py` (`compose_system_prompt`, L488-526)                       |
| v2 commands                    | `harness_poc/cli.py` (`v2_probe` L1339, `v2_gate` L1355, `v2_context` L1387)           |
| Calibrate command              | `harness_poc/cli.py` (`cartographer_calibrate`, L1256)                                 |
| Context map API                | `harness_poc/api/routes.py` (`/api/context-maps`)                                      |

### Research Notes

| Document                     | Path                                       |
| ---------------------------- | ------------------------------------------ |
| SAGE & AHE exploration notes | `docs/research/sage-ahe-self-evolution.md` |

### Other Relevant Papers (Identified but not deeply explored)

| Paper                                       | arXiv                         | Relevance                                        |
| ------------------------------------------- | ----------------------------- | ------------------------------------------------ |
| What makes a harness a harness              | 2606.10106                    | Formal definition of harness conditions          |
| LLM-as-Code Agentic Programming             | 2606.15874                    | Challenges LLM-as-orchestrator model             |
| The Semi-Executable Stack                   | 2604.15468                    | Frames competitive landscape                     |
| Rethinking How to Remember                  | 2605.19952                    | Cognitive psychology → LLM memory                |
| Multi-agent skills extension                | 2605.10052                    | Extends Anthropic Skills standard to multi-agent |
| Cognitive architectures for language agents | (TMLR 2024, Sumers/Griffiths) | Referenced but not indexed                       |

---

## 9. Design Principles (From SOUL + Pedagogy)

- **Restraint as a design virtue** — start with deterministic telemetry aggregation (Phase 1) before adding agent reasoning (Phase 2). Don't over-engineer the first pass.
- **Governed mutation** — the Evolution Agent cannot bypass verification. Its proposals are untrusted until the v2 system verifies them. HITL gates for risky changes.
- **The Evolution Agent is itself subject to PEV** — it plans, executes (in sandbox), verifies (via v2_gate), and escalates. It is not exempt from the discipline it enforces.
- **Knowledge compounds** — the AHE blackboard namespace (`ahe:*`) is a durable asset. Telemetry summaries, diagnoses, and evaluations accumulate across cycles and inform future proposals.
- **Respect the layering** — SOUL → Knowledge Skills → Executable Skills → Tool Calls. The AHE Evolution Agent is an executable skill that uses tools (calibrate, v2 system, delegate_task). It does not modify the SOUL or knowledge skills.

---

## 10. Next Steps for New Session

1. **Read this spec fully** — it's self-contained.
2. **Read the context map spec** — `docs/superpowers/specs/2026-05-23-deterministic-cartographer-design.md` — to understand materialization, eviction, and calibration mechanics. (Verify this path exists — it was referenced in code comments but may be in a different location.)
3. **Read the research notes** — `docs/research/sage-ahe-self-evolution.md` — for the SAGE/AHE exploration context.
4. **Verify the code paths** — grep for the components in §8 to confirm they match the current codebase (code may have changed).
5. **Start with Phase 1** — telemetry aggregation. This is deterministic, low-risk, and produces immediate value (a diagnostic report of harness health).
6. **Review resolved decisions in §6** — decisions locked in design review (2026-06-22).
7. **Use Vespa search** to retrieve AHE/SAGE paper content if deeper grounding is needed (commands in §8).
