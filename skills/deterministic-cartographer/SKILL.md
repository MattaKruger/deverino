---
name: deterministic-cartographer
type: knowledge
description: >
  Design rationale and migration plan for replacing the LLM-based Cartographer/Evictor
  pipeline stages with a deterministic Python priority-queue engine, based on findings
  from Kunz et al. (2025) "Compound Agent Design in Adversarial POMDPs" (2605.16205).
  Covers the three design principles, the deliberation cascade failure mode, the
  current harness architecture gap, the proposed deterministic pipeline, and concrete
  stress-test procedures drawn from the paper's ablation methodology.
version: "1.0"
---

# Deterministic Cartographer — Architecture & Migration Plan

## Source Paper

**Kunz, Bogdanov, Lung, Taylor, Zaman (2025).** *What the Agent Sees Matters More Than How Deeply It Thinks: Controlled Ablation of Compound LLM Agent Design in an Adversarial POMDP.* ACM CAIS '26.

- 72 model-configuration pairs, 3,475 episodes, 283.9M tokens across 5 model families
- Environment: CybORG CAGE-2 — 30-step adversarial POMDP, all rewards ≤ 0 (failure-mitigation mode)
- Three ablated axes: context (6 configs), deliberation (4 levels), hierarchy (2 configs)

---

## The Paper's Architecture (Four Layers)

```
Layer 1: Hierarchy       — Planner → Analyst, ActionChooser; strict JSON contracts
Layer 2: Infrastructure  — Env Model, State Machine, History Log, Action Validator (deterministic, Python)
Layer 3: Context         — YAML templates: {network_status}, {history}, {observation} (deterministic injection)
Layer 4: Reasoning       — ReAct loop, optional deliberation tools (LLM)
```

**Critical insight:** Layers 2 and 3 are deterministic code. No LLM calls. The LLM only
operates at Layer 1 (decisions) and Layer 4 (reasoning). State management, history
compression, context assembly, and action validation are all programmatic.

---

## Three Design Principles

### Principle 1: Invest in deterministic infrastructure before LLM reasoning

Programmatic state abstraction delivers 52–76% penalty reduction at near-zero marginal
token cost. Raw observations alone produce 96–98% catastrophic failure rates (< -150).
Adding deterministic `{network_status}` drops catastrophic failure to <10%.

> *"The programmatic state-tracking layer delivers the largest consistent gains per
> token by shifting the LLM from perception-plus-reasoning to reasoning-over-state."*

### Principle 2: Decompose into bounded specialists, not reflective generalists

Hierarchy without deliberation achieves best or near-best absolute performance for
4 of 6 models. The benefit is **interface constraints**: the Analyst gives a bounded
assessment, the ActionChooser a ranked list — turning open-ended generation into a
verifiable decision.

### Principle 3: Do not distribute deliberation without an uncertainty-resolution protocol

Enabling deliberation tools across a hierarchy degrades performance in **all six
models** (up to 3.4× worse return) while using 1.8–2.7× more tokens. This is the
**deliberation cascade**: a sub-agent's self-critique introduces qualifications the
consuming agent can't distinguish from genuine environmental warnings. Caution
accumulates through the hierarchy.

> *"If deliberation is needed across a hierarchy, centralize it or use explicit
> mediation (e.g., confidence gating, aggregation rules)."*

---

## The Deliberation Cascade — Diagnosis

The paper identifies the cascade through a controlled ablation. The mechanism:

1. A sub-agent (e.g., ActionChooser with deliberation tools) critiques its own output
2. The critique introduces qualifications: "Analysis shows host A is suspicious, but
   confidence is low because observation window was brief"
3. The consuming agent (Planner) receives this qualified output and adds its own
   uncertainty layer: "Analyst flagged host A with low confidence — I should monitor
   rather than act"
4. Caution compounds. Two confidence-reducing steps produce paralysis.
5. Token cost doubles because each agent runs its own deliberation loop.

---

## Current Harness Architecture Gap

The current context-map pipeline (from `2026-05-20-event-sourced-context-map-design.md`):

```
Event Store → Distiller (LLM) → Cartographer (LLM) → Evictor (budget enforcement) → Context Map
```

| Stage | Implementation | Problem |
|-------|---------------|---------|
| Distiller | LLM call — reads events, produces diagnosis + tags + raw observations | Acceptable: this is perception work the LLM should do |
| Cartographer | LLM call — receives Distiller output, decides ADD/DELETE/REPLACE, assigns sections and priority scores | **Deliberation cascade risk**: LLM reasoning about LLM output, open-ended structural decisions |
| Evictor | Deterministic budget enforcement (priority-ordered eviction) | Correct: already deterministic in the current implementation |

The Cartographer is an LLM reasoning about the Distiller's LLM output — this is
exactly the pattern that produces deliberation cascades. The Cartographer's
open-ended edit decisions (ADD/DELETE/REPLACE, section assignment, priority scoring)
introduce qualifications that the Evictor can't distinguish from genuine importance
signals.

Additionally, the Cartographer produces three operation types (ADD, DELETE, REPLACE)
with free-form content — an unbounded output contract. Principle 2 says this should
be a **verifiable decision** with a strict interface.

---

## Proposed Architecture: Deterministic Cartographer

```
Event Store → Distiller (LLM) → Deterministic Cartographer (Python) → Context Map
                    ↑                        ↑
            Strict output schema      Priority weights, token budget
```

### What stays LLM: The Distiller

The Distiller remains an LLM call. Its job is **perception** — reading raw events
and producing structured summaries. This is the paper's "reasoning-over-state"
shift: the LLM perceives, deterministic code manages state.

Critical changes to the Distiller:
1. **Strict output schema** — each observation must have: `key`, `observation_type`,
   `summary`, `source_event_ids`, `tags`. No free-form section assignment or priority
   scoring — those are Cartographer outputs.
2. **No map-entry tagging** — the Distiller no longer tags existing map entries as
   "helpful"/"harmful"/"stale". That was Cartographer reasoning injected into the
   Distiller stage. Instead, the Distiller produces **forward-only observations**.
3. **Action validation** — Distiller output is validated against the schema. Invalid
   output triggers up to 3 retries with error feedback. If all retries fail, safe
   fallback: return the last-known-good map unchanged.

### What becomes deterministic: The Cartographer + Evictor

The Cartographer and Evictor merge into a single deterministic Python function.
No LLM calls. Four operations:

```python
def deterministic_cartographer(
    distilled_observations: list[DistillerEntry],  # Distiller output (validated)
    current_map: list[MapEntry],                    # Existing map
    token_budget: int,                               # e.g. 1024
    priority_weights: dict[str, float],              # Fixed per-observation_type weights
) -> list[MapEntry]:
```

**Operation 1 — Dedup & merge:**
- Index current map by entry key
- For each Distiller observation, if key exists: replace only if source_event_ids
  are newer. Otherwise: insert.
- This replaces the Cartographer's ADD/REPLACE decision — it's a deterministic
  novelty check, not an LLM judgment call.

**Operation 2 — Priority scoring:**
- Each entry gets a deterministic priority score:
  `base_weight[observation_type] + recency_bonus * event_timestamp`
- Priority weights are fixed per observation type (e.g., `entity: 0.7`, `schema: 0.8`,
  `insight: 0.9`, `dispute: 1.0`).
- No LLM judgment about "how valuable" an entry is — the weight table encodes
  organizational priorities.

**Operation 3 — Deleting stale entries:**
- Entries not seen in the last N materialization cycles drop in priority by a
  staleness penalty. If priority falls below a floor, the entry is removed.
- This is a deterministic time-based decay, not an LLM "harmful"/"stale" tag.
- Tag-driven deletion is removed — the Distiller no longer tags existing entries.

**Operation 4 — Budget enforcement:**
- Sort by priority, descending
- Take entries until token budget is exhausted
- Remaining entries are evicted (with derivation events emitted)

### Distiller Output Schema (New Contract)

```python
class DistillerEntry:
    key: str                    # Stable slug (e.g., "codebase-entry-point")
    observation_type: str       # "entity", "schema", "insight", "dispute", "boundary"
    summary: str                # One-paragraph orientation fact
    source_event_ids: list[str] # Event IDs supporting this observation
    tags: list[str]             # "confirmed", "novel", "correcting" (descriptive only)
    # NO section assignment — Cartographer assigns this
    # NO priority score — Cartographer computes this
    # NO map operation hints — Cartographer decides

class MapEntry:
    entry_id: str               # UUID, stable across map versions
    key: str                    # Slug, matches DistillerEntry.key
    section: str                # Assigned deterministically by Cartographer
    observation_type: str
    summary: str
    priority: float             # Computed deterministically
    source_event_ids: list[str]
    first_seen: datetime
    last_updated: datetime
    materialization_count: int  # How many times this entry has survived eviction
```

### Section Assignment (Deterministic)

The Cartographer assigns sections based on `observation_type`, not LLM judgment:

| observation_type | section |
|-----------------|---------|
| `schema` | `parsing_schema` |
| `entity` | `context_understanding` |
| `insight` | `context_roadmap` |
| `boundary` | `context_understanding` |
| `dispute` | `context_roadmap` |
| `constant` | `domain_constants` |
| `result` | `reusable_results` |

### Priority Weights (Configurable)

```yaml
# In harness.yaml — tunable per project
cartographer_priority_weights:
  dispute: 1.0       # Correcting errors is highest priority
  schema: 0.9         # Schema knowledge prevents tool failures
  insight: 0.8        # Non-obvious relationships
  boundary: 0.7       # What's NOT in the corpus — prevents hallucination
  entity: 0.6         # Key classes/functions/modules
  result: 0.5         # Reusable computation results
  constant: 0.4       # Domain constants (rarely change)

cartographer_recency_bonus: 0.01   # Per-materialization cycle
cartographer_staleness_penalty: 0.05  # Per missed cycle
cartographer_staleness_floor: 0.2     # Below this, entry is evicted
```

### Action Validation (from Paper's Reliability Mechanisms)

The paper's action validator maps directly to Distiller output validation:

1. **Schema validation**: Distiller JSON is parsed against the `DistillerEntry` schema
2. **Up to 3 retries**: Invalid output → inject parsing error as feedback → retry
3. **Safe fallback**: All retries failed → return last-known-good map unchanged
   (analogous to the paper's `Monitor` fallback — preserves observability, does no harm)
4. **Any retry calls are included in token accounting**

---

## Why This Follows the Paper's Principles

| Paper Principle | How the Deterministic Cartographer Implements It |
|----------------|--------------------------------------------------|
| P1: Deterministic before LLM | Distiller (LLM perception) → Cartographer (deterministic state management). The LLM reasons over state; deterministic code decides what state to keep. |
| P2: Bounded specialists, not reflective generalists | Distiller has a strict output schema with fixed fields. Cartographer has a fixed algorithm (priority queue, dedup, budget cap). No open-ended "what should I do with this?" LLM calls. |
| P3: No distributed deliberation without arbitration | Single LLM call (Distiller) → deterministic mediation (Cartographer). No chain of LLM calls where each reasons about the previous output. |
| Step-level instantiation | Each materialization is a fresh Distiller call. No hidden conversational state accumulates across materialization cycles. All inter-cycle continuity is in the deterministic map entries. |
| Action validation + retry + safe fallback | Distiller output validated against schema; 3 retries; fallback to last-known-good map. |

---

## Stress Test Procedures

Based on the paper's ablation methodology, four stress tests to validate the migration:

### Test 1: Deliberation Cascade Detection (Current Pipeline)

**Purpose:** Measure whether the current LLM Cartographer exhibits cascading uncertainty.

**Procedure:**
1. Feed the same observation event through N=10 independent materialization runs
2. For each run, capture: which entries were added/modified/deleted, what priority
   scores were assigned, what sections entries landed in
3. Measure edit-level agreement across runs (Jaccard similarity of entry key sets,
   Fleiss' kappa for section assignment, standard deviation of priority scores)
4. If variance is high (>20% disagreement on edits, >0.3 std dev on priorities),
   the pipeline has a deliberation cascade

**Paper grounding:** The paper detected cascades by comparing monolithic vs.
hierarchical deliberation. Our analog: repeated materialization of identical input
should produce identical output if the pipeline is deterministic. Variance in the
LLM Cartographer stage reveals cascading uncertainty.

### Test 2: Deterministic Cartographer Parity

**Purpose:** Verify the deterministic Cartographer produces map quality at least
equal to the LLM Cartographer, at lower token cost.

**Procedure:**
1. Run N materialization cycles with the **LLM Cartographer** (current). Record:
   token cost per cycle, map entries produced, downstream task accuracy (can the
   agent find the right document/entity with this map?)
2. Run the same N cycles with the **deterministic Cartographer** (new). Same metrics.
3. Compare: token cost (expect >50% reduction — one LLM call instead of two),
   map quality (expect parity or improvement), stability (expect zero variance
   on repeated input)

**Paper grounding:** Finding 1 — "programmatic state abstraction delivers the
largest gains per token." The deterministic Cartographer is programmatic state
abstraction applied to the map management layer.

### Test 3: Token Budget Ablation

**Purpose:** Find the efficient frontier for map token budget.

**Procedure:**
1. Ablate token budget at [256, 512, 1024, 2048, 4096]
2. For each budget: run a standard task suite, measure accuracy and token cost
3. Plot cost-performance frontier
4. Identify the budget where diminishing returns set in

**Paper grounding:** Finding 3 — "less-but-structured often beats more-but-unstructured."
The paper found that `hist+net` (structured state + history, no raw observations)
matched or beat the maximum-information `obs+hist+net` configuration.

### Test 4: Schema Contract Violation Recovery

**Purpose:** Verify the action validation + retry + safe fallback mechanism.

**Procedure:**
1. Intentionally corrupt Distiller output: drop required fields, inject malformed
   JSON, produce empty observations
2. Verify the validator catches each violation
3. Verify retry with error feedback produces corrected output (for recoverable errors)
4. Verify safe fallback to last-known-good map (for unrecoverable errors)
5. Verify no partial map writes (atomic transaction)

**Paper grounding:** The paper's reliability mechanisms — "every invalid action is
a wasted step during which the attacker advances unopposed." In our context, every
invalid map update is a wasted materialization cycle with a degraded map.

---

## Migration Path

### Phase 1: Schema Hardening (no pipeline change)

1. Define `DistillerEntry` and `MapEntry` as Pydantic models
2. Add schema validation to Distiller output in the current pipeline
3. Add retry logic: 3 attempts with error feedback, safe fallback
4. Emit derivation events for validation failures and retries
5. This adds reliability without changing the LLM Cartographer

### Phase 2: Deterministic Cartographer (parallel)

1. Implement `deterministic_cartographer()` as a pure function
2. Add `cartographer_priority_weights` to `harness.yaml` with defaults
3. Run both pipelines in parallel on the same events, compare output
4. Log divergence: where does the LLM Cartographer make different decisions?
5. Tune weights based on divergence analysis

### Phase 3: Cutover

1. Replace `_cartographer_messages()` + `_apply_edits()` + `_enforce_budget()` with
   `deterministic_cartographer()` call
2. Remove the LLM Cartographer prompt from the skill
3. Keep the Distiller LLM call unchanged (only output validation added)
4. Update token accounting: one LLM call per materialization instead of two

### Phase 4: Observability

1. Emit derivation events for each Cartographer decision (merge, score, evict)
2. Add `cartographer_decision_log` to blackboard for debugging
3. Replay: rebuild map from event stream using deterministic Cartographer
   (now fully deterministic — same events → same map, always)

---

## Open Questions

1. **Priority weight tuning.** The initial weights are defaults. Should they be
   learned from usage patterns (which entries the agent actually references)?
2. **Section assignment granularity.** Five sections may be too many or too few.
   Does the deterministic `observation_type → section` mapping cover all cases?
3. **Staleness decay rate.** The penalty of 0.05 per missed cycle is arbitrary.
   Needs empirical calibration — how many cycles before a once-valuable entry
   becomes noise?
4. **Multi-corpus interaction.** When an agent switches between corpora, should
   cross-corpus insights (e.g., "codebase entity X corresponds to wiki concept Y")
   be handled by the Cartographer or by a separate cross-corpus materializer?
5. **Distiller model choice.** With only one LLM call, the Distiller must be good
   enough. Does the current model produce adequate structured summaries under the
   strict output schema?

---

## References

- Kunz et al. (2025): `docs/papers_2/2605.16205.pdf` — primary source
- PEEK paper: `docs/papers/2605.19932.pdf` — context map concept origin
- Event-sourced context map design: `docs/superpowers/specs/2026-05-20-event-sourced-context-map-design.md`
- Context map implementation spec: `docs/superpowers/specs/2026-05-20-context-map-implementation-spec.md`
- Freeze & derivation IDs: `docs/superpowers/specs/2026-07-23-context-map-freeze-derivation-ids.md`
- ACDL spec: `deverino_react.acdl` — ContextMapBlock injection point
- SDB paper (2605.20173): `docs/papers/2605.20173.pdf` — complementary pattern catalog
