# Sprint Contract Integration for delegate_task

**Status:** Draft
**Date:** 2026-05-23
**Scope:** `harness_poc/system_skills/delegate_task/` — add Sprint Contract protocol to existing sub-agent delegation without new runtime components.

---

## 1. Motivation

### 1.1 Current state

`delegate_task` spawns a sub-agent, gives it a persona template and an objective, and accepts whatever structured output it returns. The contract is: "do your best, tell me what happened."

```
Orchestrator ──[persona + objective]──► Sub-agent ──[{status, summary, artifacts}]──► Blackboard
```

There is no deliverable enumeration, no success criteria, no post-execution gate. The sub-agent can return `status: "completed"` having done nothing verifiable, and the orchestrator has no mechanism to detect this.

### 1.2 buddyMe Sprint Contract findings

The buddyMe research project found that structured contracts with deterministic gates significantly improve multi-agent reliability. Three engineering lessons from §7.2 transfer directly to our sub-agent delegation — with important caveats verified against the paper:

| Lesson                            | Paper finding (§7.2)                                                                                               | Application to delegate_task                                                           | Paper fidelity                                                                                                                                                                                                                |
| --------------------------------- | ------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Context isolation**             | Executor-evaluator shared client inflated scores by +0.12. Fixed by three-client isolation (§3.2).                 | Sub-agent already gets its own `Agent()` instance — we preserve this property.         | **Domain-shifted**: paper's evidence is about Evaluator-Executor bias in adversarial review; our architecture is orchestrator-sub-agent. Lesson transfers but empirical values (+0.12) were collected in a different context. |
| **Numerical > boolean**           | LLMs produced `score=0.8` with `approved=False`. Switching to `score >= 0.8` resolved it (§4.1, §7.2 Lesson 2).    | Gate uses only numeric checks (`confidence >= 0.5`, array lengths) — no boolean field. | **Clean mapping**: the finding is verbatim. Our gate is purely numeric.                                                                                                                                                       |
| **Data collection ≠ consumption** | MessageHistory recorded dialogues but never transmitted to TaskRunner — catastrophic context loss (§7.2 Lesson 3). | Contract results must pass a gate before blackboard acceptance.                        | **Pattern only**: paper describes inter-component wiring within a single framework; our mechanism is output gating, not input wiring. Pattern inspiration, not direct application.                                            |

Additionally, buddyMe §5 describes **post-execution requirement alignment** — passing the Sprint Contract to the evaluation phase as a baseline reference, verifying deliverables against outputs and success criteria against measurable outcomes. This post-execution alignment is structurally closer to our output gate than the pre-execution Generator-Evaluator review. The paper does both phases; we are implementing only the post-execution side.

### 1.3 What we're adding

A thin protocol layer on top of the existing `delegate_task` infrastructure:

1. **Optional `contract` argument** — deliverables list + success criteria list + task label
2. **Extended `DelegatedTaskOutput`** — 4 new fields for contract-aware results
3. **Deterministic gate** — `_passes_gate()` that runs in `execute()` before writing to blackboard
4. **Enhanced persona template** — system prompt that instructs the sub-agent how to fulfill a contract
5. **Richer events** — contract fields in `SubAgentCompleted`

No new skills. No new runtime. No FSM. Same execution path, enriched output schema.

---

## 2. Design

### 2.1 Data model changes

#### 2.1.1 DelegatedTaskOutput (skill.py)

```python
class DelegatedTaskOutput(BaseModel):
    status: Literal["completed", "failed", "blocked"] = "completed"
    summary: str
    artifacts: dict[str, Any] = Field(default_factory=dict)

    # --- NEW: Sprint Contract fields ---
    deliverables: list[str] = Field(
        default_factory=list,
        description="Actual deliverables produced. One entry per item."
    )
    criteria_results: dict[str, bool] = Field(
        default_factory=dict,
        description="Per-criterion pass/fail. Keys match contract criteria."
    )
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Sub-agent self-assessment of result quality."
    )
    evidence: list[str] = Field(
        default_factory=list,
        description="Files, documents, or sources actually consulted to produce the result."
    )
```

New fields are **optional with defaults** — backward compatible with existing callers that don't provide a contract. When no contract is given, the sub-agent fills defaults and the gate is skipped.

#### 2.1.2 Contract argument shape

```python
contract: dict[str, Any] | None
# When provided:
{
    "deliverables": [
        "A prioritized list of N test cases",
        "A risk assessment table covering 5 dimensions",
    ],
    "success_criteria": [
        "Every test case references at least one source file",
        "Risk table has non-empty entries for all 5 dimensions",
        "Output is valid JSON",
    ],
    "task_label": "RESEARCH"  # one of: SEARCH | CREATE | EDIT | VERIFY | RESEARCH
}
```

#### 2.1.3 SubAgentCompleted event (events.py)

```python
class SubAgentCompleted(BaseEvent):
    sub_session_id: str
    status: str
    content: str

    # --- NEW ---
    deliverables_count: int = 0
    criteria_passed: int = 0
    criteria_total: int = 0
    confidence: float | None = None
    evidence_count: int = 0
    gate_passed: bool | None = None
```

### 2.2 Execution flow

```
execute(ctx, arguments)
  │
  ├─ 1. Parse persona, objective, memory_key, context, contract (NEW)
  │
  ├─ 2. Load persona template from personas/ directory
  │
  ├─ 3. _build_subagent_prompt(objective, context, contract=contract)  ← ENHANCED
  │      │
  │      └─ If contract provided, inject into prompt:
  │           "Execute this delegated task against a Sprint Contract.
  │            Deliverables (you must address each): ...
  │            Success criteria (your output must satisfy): ...
  │            Task label: RESEARCH
  │            Populate deliverables[], criteria_results{}, confidence, evidence."
  │
  ├─ 4. _run_subagent(persona_template, prompt) → DelegatedTaskOutput
  │
  ├─ 5. _passes_gate(output, contract)  ← NEW DETERMINISTIC GATE
  │      │
  │      ├─ No contract → True (backward compatible)
  │      ├─ confidence < 0.5 → False
  │      ├─ len(evidence) == 0 → False
  │      ├─ len(deliverables) == 0 → False
  │      └─ Otherwise → True
  │
  ├─ 6. Store result in blackboard under memory_key
  │      │
  │      └─ If gate failed: status overridden to "blocked",
  │         gate_failure_reason appended to artifacts
  │
  ├─ 7. Emit SubAgentCompleted event with contract fields  ← ENHANCED
  │
  └─ 8. Return SkillResult
```

### 2.3 Gate logic

```python
def _passes_gate(output: DelegatedTaskOutput, contract: dict | None) -> tuple[bool, str]:
    """Deterministic gate. Returns (passed, failure_reason)."""
    if contract is None:
        return True, ""

    if output.confidence < 0.5:
        return False, f"confidence {output.confidence:.2f} below threshold 0.5"

    if len(output.evidence) == 0:
        return False, "no evidence cited"

    if len(output.deliverables) == 0:
        return False, "no deliverables produced"

    return True, ""
```

The gate is **not configurable by the sub-agent** — it runs in `execute()` after the sub-agent returns, in the orchestrator's process. The sub-agent cannot bypass it.

### 2.4 Prompt injection

In `_build_subagent_prompt()`, when `contract` is provided, append:

```python
def _build_subagent_prompt(*, objective: str, context: str, contract: dict | None = None) -> str:
    context_section = context or "No additional context was provided."

    prompt = (
        "Execute this delegated read-only research task.\n\n"
        f"Objective:\n{objective}\n\n"
        f"Context:\n{context_section}\n\n"
    )

    if contract:
        deliverables = contract.get("deliverables", [])
        criteria = contract.get("success_criteria", [])
        task_label = contract.get("task_label", "RESEARCH")

        prompt += (
            "Sprint Contract:\n"
            f"  Task label: {task_label}\n"
            f"  Deliverables (you must address each):\n"
        )
        for i, d in enumerate(deliverables, 1):
            prompt += f"    D{i}: {d}\n"

        prompt += "  Success criteria (your output must satisfy):\n"
        for i, c in enumerate(criteria, 1):
            prompt += f"    C{i}: {c}\n"

        prompt += (
            "\n"
            "Return a structured result. In your output:\n"
            "- Populate 'deliverables' with one summary string per deliverable you actually produced.\n"
            "- Populate 'criteria_results' with a boolean pass/fail for each criterion.\n"
            "- Set 'confidence' to your self-assessment (0.0-1.0).\n"
            "- Populate 'evidence' with specific files, documents, or sources you consulted.\n"
        )
    else:
        prompt += (
            "Return a concise structured result with status, summary, and artifacts. "
            "Use artifacts for important findings, caveats, and suggested next steps."
        )

    return prompt
```

### 2.5 Persona template for Sprint Contracts

Create `personas/researcher.md` (the first persona):

```markdown
You are a Sprint Contract researcher. You execute delegated read-only
research tasks against a structured contract of deliverables and
success criteria.

When you receive a contract:

1. Read the deliverables list — these are WHAT you must produce
2. Read the success criteria — these are HOW your output will be judged
3. Read the task label — this tells you the work mode
4. Execute the objective against the contract
5. Return structured output with specific, verifiable results

Modes:

- SEARCH: Find information, files, patterns. Produce a findings report.
- RESEARCH: Investigate deeply. Produce analysis with citations.
- VERIFY: Check something against criteria. Produce pass/fail with evidence.

Rules:

- Every claim in your summary must be traceable to something in evidence.
- If you cannot fulfill a deliverable, state that explicitly in the
  corresponding deliverables[] entry.
- Set confidence honestly — 0.5 means "best effort but uncertain,"
  1.0 means "fully verified with complete evidence."
- Never fabricate evidence citations. Only cite what you actually consulted.
```

---

## 3. Implementation steps

### Step 1: Extend DelegatedTaskOutput

**File:** `harness_poc/system_skills/delegate_task/skill.py`

Add 4 fields to the Pydantic model: `deliverables`, `criteria_results`, `confidence`, `evidence`. All have defaults — no callers break. Run existing tests.

### Step 2: Add contract parsing in execute()

**File:** `harness_poc/system_skills/delegate_task/skill.py`

Parse optional `contract` from `arguments`. Pass through to `_build_subagent_prompt()` and `_passes_gate()`. Run existing tests.

### Step 3: Add \_build_subagent_prompt() contract branch

**File:** `harness_poc/system_skills/delegate_task/skill.py`

Add `contract` parameter. When non-None, inject deliverables/criteria/task_label into prompt. Add instructions for populating the new output fields.

### Step 4: Add \_passes_gate()

**File:** `harness_poc/system_skills/delegate_task/skill.py`

Pure function: `(output, contract) → (bool, reason)`. Called in `execute()` after sub-agent returns. On failure, override status to `"blocked"` and append `gate_failure_reason` to the result before storing.

### Step 5: Extend SubAgentCompleted event

**File:** `harness_poc/core/events.py`

Add 5 optional fields to `SubAgentCompleted`. The event is emitted by the calling site (goal_runner or pipeline_runner), not by the skill itself — the skill stores contract data in the blackboard result.

### Step 6: Create personas/researcher.md

**File:** `personas/researcher.md` (new file)

First persona. Sprint Contract-aware system prompt with mode descriptions and citation rules.

### Step 7: Update SKILL.md

**File:** `harness_poc/system_skills/delegate_task/SKILL.md`

Document the new `contract` parameter. Update behavior section. Bump version to 1.1.

### Step 8: Add tests

**File:** `tests/test_delegate_task.py` (or wherever delegate_task tests live)

- Test: no contract → backward compatible output
- Test: contract provided → new fields populated
- Test: gate passes with confidence=0.8, evidence, deliverables
- Test: gate blocks with confidence=0.3
- Test: gate blocks with empty evidence
- Test: prompt includes contract fields when provided

### Step 9: End-to-end integration test

Send a real `delegate_task` call with contract, verify:

- Sub-agent receives contract in prompt
- Output contains populated deliverables/criteria_results/confidence/evidence
- Gate passes or fails appropriately
- Blackboard entry has contract fields
- SubAgentCompleted event has contract counts

---

## 4. What does NOT change

- **No new skills** — the Sprint Contract is not a separate skill, it's a protocol on top of `delegate_task`
- **No runtime changes** — same `Agent()` instantiation, same streaming, same blackboard
- **No FSM** — the gate is a single function call in `execute()`, not a state machine
- **No LLM merge step** — the gate is deterministic Python, no LLM decides acceptance
- **Existing callers unaffected** — `contract` is optional, new fields have defaults, the prompt only changes when contract is provided

## 5. Relationship to plan-mode-v2

The plan-mode-v2 spec (`docs/plans/20260521-plan-mode-vespa-embedding-v2.md`) described a larger Sprint Contract generator that:

1. Drafts a requirement document (summary, deliverables, criteria, approach, risks, tagged plan)
2. Has it evaluated by an adversarial LLM on 4 axes
3. Pushes to Vespa for retrieval
4. Is reviewed by a human

That design and this one are **compatible**:

| Layer             | plan-mode-v2 (future)                    | delegate_task Sprint Contract (this design)    |
| ----------------- | ---------------------------------------- | ---------------------------------------------- |
| Contract author   | LLM generator + evaluator                | Orchestrator (or plan-mode output)             |
| Contract consumer | Human reads from Vespa                   | `delegate_task` sub-agent                      |
| Gate              | 4 deterministic checks before Vespa feed | 3 deterministic checks before blackboard write |
| Schema            | Full SprintContract JSON                 | Extended DelegatedTaskOutput                   |

When plan-mode-v2 is built, its output can directly populate the `contract` argument to `delegate_task`. The same schema vocabulary (deliverables, success_criteria, task_label) flows end-to-end.

---

## 6. Paper Verification

_Cross-referenced against buddyMe (2605.16821) using the paper-claim-verification skill. The paper's full text was searched for each claim attributed to it._

### Claim-by-claim verification

| #   | Claim in design doc                                                                                                           | Paper's actual content                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     | Verdict                                       | Correction needed                                                                                                                                                                                                                                                                                                                                                                                                                    |
| --- | ----------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 1   | "buddyMe Sprint Contract findings: structured contracts with deterministic gates significantly improve sub-agent reliability" | buddyMe §4.1: Sprint Contract is a **pre-execution** Generator-Evaluator adversarial review mechanism. The "gate" is an LLM Evaluator scoring the plan against 4 criteria (completeness, verifiability, coverage, risk) with `score >= 0.8` approval. It operates BEFORE task execution, on the PLAN, not on sub-agent OUTPUT.                                                                                                                                                                                                             | **Domain-shifted**                            | The Sprint Contract name applies to a pre-execution plan validation mechanism. This design inverts it to post-execution output gating. Rename or clearly distinguish: "Sprint Contract-inspired output gate" rather than "Sprint Contract."                                                                                                                                                                                          |
| 2   | "Context isolation: Shared LLM client inflated confidence scores by +0.12"                                                    | buddyMe §3.2 + §7.2 Lesson 1: "In the initial implementation, the executor and evaluator shared a single LLM client, causing evaluation scores to be systematically inflated by an average of +0.12." This is about **evaluator-executor** bias in the adversarial review architecture.                                                                                                                                                                                                                                                    | **Clean mapping, domain-shifted application** | The finding is accurate, but buddyMe's context isolation is between Evaluator and Executor in an adversarial loop. In delegate_task, the sub-agent already gets its own `Agent()` instance — we preserve this property but in a simpler architecture (orchestrator-sub-agent rather than executor-evaluator). The lesson transfers: don't let the gate-sharer see the executor's context.                                            |
| 3   | "Numerical > boolean: LLMs produce score=0.8 with approved=False"                                                             | buddyMe §7.2 Lesson 2 + §4.1: "LLMs frequently produced score=0.8 with approved=False, revealing internal inconsistency between numerical and boolean judgments. Switching to score-only approval resolved this issue." Approval condition: `score >= 0.8`, **not** `approved=True AND score >= 0.8`.                                                                                                                                                                                                                                      | **Clean mapping**                             | The finding is verbatim from the paper. Our gate uses only numeric checks (`confidence >= 0.5`, array lengths) with no boolean field — consistent with the lesson.                                                                                                                                                                                                                                                                   |
| 4   | "Data collection ≠ consumption: MessageHistory was recorded but never read back"                                              | buddyMe §7.2 Lesson 3: "The MessageHistory component correctly recorded session dialogues, but this data was never transmitted to the TaskRunner. This caused catastrophic context loss." This is about internal buddyMe component wiring (MessageHistory → TaskRunner).                                                                                                                                                                                                                                                                   | **Pattern only**                              | The paper's lesson is about inter-component data flow within a single framework. Our mapping — "contract results must pass a gate before blackboard acceptance" — is a different mechanism (output gating, not input wiring). Reclassify: pattern inspiration, not direct application.                                                                                                                                               |
| 5   | `confidence >= 0.5` threshold                                                                                                 | buddyMe uses `score >= 0.8` for PlanReviewer approval (plan_reviewer.py:314). The value `0.5` appears only as the efficiency dimension score in a case study (§7.3), an entirely unrelated context.                                                                                                                                                                                                                                                                                                                                        | **Wrong attribution**                         | The 0.5 threshold has **zero paper basis**. It is a heuristic initial value. The design doc's §7 already lists this as a risk with mitigation "tune with data" but does not acknowledge the disconnect from the cited paper. Must be explicitly flagged as **heuristic, not paper-validated**.                                                                                                                                       |
| 6   | Task labels include `RESEARCH`                                                                                                | buddyMe §4.1 lists task labels as `[SEARCH]/[CREATE]/[EDIT]/[VERIFY]`. `RESEARCH` does not appear in the buddyMe paper.                                                                                                                                                                                                                                                                                                                                                                                                                    | **Extension, not from paper**                 | `RESEARCH` was added in plan-mode-v2 as an extension. This design inherits it. Not wrong, but must attribute correctly: `SEARCH/CREATE/EDIT/VERIFY` are from buddyMe; `RESEARCH` is a Deverino extension.                                                                                                                                                                                                                            |
| 7   | "Sprint Contract" as a deliverable-gating protocol                                                                            | buddyMe's Sprint Contract is: (1) generated by a Generator LLM, (2) evaluated by an independent Evaluator LLM, (3) in adversarial multi-round discussion (95% converge in 2-3 rounds), (4) BEFORE task execution. Our design: contract is provided by the orchestrator, gate is deterministic Python, single-pass, AFTER sub-agent execution.                                                                                                                                                                                              | **Architectural inversion**                   | Four structural differences: pre- vs post-execution, LLM-generated vs orchestrator-provided, LLM-evaluated vs deterministic-gated, multi-round vs single-pass. The only shared element is the schema vocabulary (deliverables, success criteria, task labels).                                                                                                                                                                       |
| 8   | Our design omits post-execution requirement alignment                                                                         | buddyMe §5: "A distinguishing feature of buddyMe's evaluation is the integration of the Sprint Contract into post-execution assessment. The requirement document generated during pre-review is passed to the evaluation phase as a baseline reference." The evaluation prompt instructs the LLM to verify deliverables against outputs, check success criteria against measurable outcomes, assess plan-execution overlap, and identify missing items. This is structurally closer to our output gate than the §4.1 pre-execution review. | **Missing phase**                             | The paper has a TWO-phase Sprint Contract lifecycle: pre-execution review (§4.1) AND post-execution alignment (§5). Our design implements only the post-execution side of this, but without the pre-execution contract generation + adversarial review that the paper couples it with. The closed-loop quality assurance (define success → execute → measure against definition) is the paper's contribution; we have half the loop. |

### Structural differences from buddyMe Sprint Contract

| Dimension               | buddyMe Sprint Contract                                                                      | This design                                                                                         |
| ----------------------- | -------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| **Phase**               | Pre-execution (plan validation)                                                              | Post-execution (output gating)                                                                      |
| **Contract author**     | Generator LLM (sub_client)                                                                   | Orchestrator (human or plan-mode output)                                                            |
| **Evaluator**           | Independent LLM (eval_client) on 4 qualitative criteria                                      | Deterministic Python on 3 quantitative checks                                                       |
| **Rounds**              | Multi-round adversarial (2-3, 95% converge)                                                  | Single-pass                                                                                         |
| **Approval threshold**  | `score >= 0.8` (LLM-assigned)                                                                | `confidence >= 0.5` (sub-agent self-assessed)                                                       |
| **Real verification**   | Runs generated code, collects stdout/stderr                                                  | Structural only (array lengths, numeric comparison)                                                 |
| **Post-exec alignment** | §5: evaluates outputs against Sprint Contract (deliverables_met, criteria_met, plan_overlap) | Our gate checks deliverables/evidence presence but doesn't align against original contract criteria |
| **Task labels**         | SEARCH, CREATE, EDIT, VERIFY                                                                 | + RESEARCH (Deverino extension)                                                                     |

### Known contradictions and unresolved tensions

1. **Confidence threshold is heuristic, not paper-validated.** buddyMe uses `0.8` for plan approval; we use `0.5` for output gating. These are different distributions (Evaluator-assigned vs self-assessed) and the 0.5 value has no empirical basis. Flag for calibration after collecting real usage data.

2. **Sprint Contract architectural inversion.** buddyMe validates plans BEFORE execution; we gate output AFTER execution. The name "Sprint Contract" suggests pre-execution review. Consider renaming to "Delegation Contract" or "Output Gate" to avoid implying the buddyMe architecture.

3. **No adversarial review.** buddyMe's 20% requirement-omission capture is demonstrated WITH adversarial Generator-Evaluator discussion. Without adversarial review, the benefits may not transfer. Our design explicitly notes this in §5 (Relationship to plan-mode-v2) — the full adversarial loop is tracked as future work.

4. **RESEARCH task label is a Deverino extension.** Not in buddyMe. Plan-mode-v2 added it; this design inherits it. Should be explicitly attributed.

5. **Three Lessons are pattern transfer, not direct application.** All three buddyMe lessons (§7.2) describe internal Evaluator-Defender architecture issues. Our application to orchestrator-sub-agent delegation is valid pattern transfer, but the paper's empirical evidence (+0.12 bias correction, score-only approval) was collected in a different architectural context.

---

## 7. Risks

| Risk                                               | Likelihood | Mitigation                                                                                                                                                                                                   |
| -------------------------------------------------- | ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Sub-agent "hallucinates" evidence citations        | Medium     | Gate only requires non-empty list, not citation validation. Future: verify against workspace files.                                                                                                          |
| confidence=0.5 threshold is too low/high           | Low        | 0.5 is deliberately permissive — it only catches "I clearly failed." Tune with data.                                                                                                                         |
| Persona template doesn't enforce contract behavior | Medium     | The prompt injection is the binding mechanism. Persona is supplementary instruction. If the model ignores the contract, the gate catches it.                                                                 |
| contract schema drifts from plan-mode-v2           | Low        | Use same field names. Add a `contract_version` field later if divergence becomes an issue.                                                                                                                   |
| No post-execution requirement alignment (§5)       | Medium     | buddyMe's full cycle passes the Sprint Contract from pre-review into post-execution evaluation for closed-loop alignment. Our post-execution-only gate skips this feedback loop. Track as future work in §5. |
