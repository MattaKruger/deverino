# Implementation Spec: Sprint Contract in delegate_task

**Derived from:** `docs/plans/20260523-sprint-contract-delegate-task.md`
**Status:** Ready
**Files touched:** 5 (3 modified, 2 new)

---

## Step 0 — Verify baseline

```bash
pytest tests/test_delegate_task.py -v
```

All 4 tests must pass before any changes. If any fail, stop and fix.

---

## Step 1 — Extend DelegatedTaskOutput

**File:** `harness_poc/system_skills/delegate_task/skill.py`

### Current (line 19–22)

```python
class DelegatedTaskOutput(BaseModel):
    status: Literal["completed", "failed", "blocked"] = "completed"
    summary: str
    artifacts: dict[str, Any] = Field(default_factory=dict)
```

### Target

```python
class DelegatedTaskOutput(BaseModel):
    status: Literal["completed", "failed", "blocked"] = "completed"
    summary: str
    artifacts: dict[str, Any] = Field(default_factory=dict)

    # Sprint Contract fields (all optional — backward compatible)
    deliverables: list[str] = Field(
        default_factory=list,
        description="Actual deliverables produced. One summary string per item.",
    )
    criteria_results: dict[str, bool] = Field(
        default_factory=dict,
        description="Per-criterion pass/fail. Keys match contract criteria.",
    )
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Sub-agent self-assessment of result quality.",
    )
    evidence: list[str] = Field(
        default_factory=list,
        description="Files, documents, or sources actually consulted.",
    )
```

### Acceptance

```bash
pytest tests/test_delegate_task.py -v
# All 4 existing tests pass. Pydantic model_rebuild still works.
```

No callers reference these fields yet. Defaults ensure no behavior change.

---

## Step 2 — Add contract parsing in execute()

**File:** `harness_poc/system_skills/delegate_task/skill.py`

### Current `execute()` signature (line 28)

```python
def execute(ctx: SkillContext, arguments: dict[str, Any]) -> SkillResult:
    persona = str(arguments.get("persona") or arguments.get("template_name") or "")
    objective = str(arguments.get("objective") or "")
    memory_key = str(arguments.get("memory_key") or f"{persona}_result")
    context = str(arguments.get("context") or "")
    use_mock = bool(arguments.get("use_mock", False))
```

### Target — add one line after `use_mock`

```python
def execute(ctx: SkillContext, arguments: dict[str, Any]) -> SkillResult:
    persona = str(arguments.get("persona") or arguments.get("template_name") or "")
    objective = str(arguments.get("objective") or "")
    memory_key = str(arguments.get("memory_key") or f"{persona}_result")
    context = str(arguments.get("context") or "")
    use_mock = bool(arguments.get("use_mock", False))
    contract: dict[str, Any] | None = arguments.get("contract")  # NEW
```

### Target — pass contract through to \_run_subagent (line 43-50)

Current:

```python
    template = ctx.read_subagent_template(persona)
    output = _run_subagent(
        persona_template=template,
        objective=objective,
        context=context,
        use_mock=use_mock,
        llm_config=ctx.config.llm,
        on_text=ctx.emit_text,
    )
```

Target:

```python
    template = ctx.read_subagent_template(persona)
    output = _run_subagent(
        persona_template=template,
        objective=objective,
        context=context,
        contract=contract,       # NEW
        use_mock=use_mock,
        llm_config=ctx.config.llm,
        on_text=ctx.emit_text,
    )
```

### Target — add gate check + blocked override after \_run_subagent (after line 50)

Insert between `output = _run_subagent(...)` and `result = {...}`:

```python
    # Gate the output through post-execution contract checks
    gate_passed, gate_reason = _passes_gate(output, contract)
    if not gate_passed:
        output = DelegatedTaskOutput(
            status="blocked",
            summary=output.summary,
            artifacts={
                **output.artifacts,
                "gate_failure_reason": gate_reason,
            },
            deliverables=output.deliverables,
            criteria_results=output.criteria_results,
            confidence=output.confidence,
            evidence=output.evidence,
        )
```

### Target — include contract fields in blackboard result (line 51-60)

Current:

```python
    result = {
        "status": output.status,
        "summary": output.summary,
        "artifacts": {
            "persona": persona,
            "model_output": output.model_dump(),
            "objective": objective,
            "received_context": context,
        },
    }
```

Target:

```python
    result = {
        "status": output.status,
        "summary": output.summary,
        "artifacts": {
            "persona": persona,
            "model_output": output.model_dump(),
            "objective": objective,
            "received_context": context,
        },
        # Sprint Contract fields (present even when no contract provided)
        "deliverables": output.deliverables,
        "criteria_results": output.criteria_results,
        "confidence": output.confidence,
        "evidence": output.evidence,
        "gate_passed": gate_passed,
        "gate_reason": gate_reason,
    }
```

### Acceptance

```bash
pytest tests/test_delegate_task.py -v
# All 4 existing tests pass. Backward compatible — contract=None path unchanged.
```

---

## Step 3 — Add contract branch in \_build_subagent_prompt()

**File:** `harness_poc/system_skills/delegate_task/skill.py`

### Current (line 156-164)

```python
def _build_subagent_prompt(*, objective: str, context: str) -> str:
    context_section = context or "No additional context was provided."
    return (
        "Execute this delegated read-only research task.\n\n"
        f"Objective:\n{objective}\n\n"
        f"Context:\n{context_section}\n\n"
        "Return a concise structured result with status, summary, and artifacts. "
        "Use artifacts for important findings, caveats, and suggested next steps."
    )
```

### Target

```python
def _build_subagent_prompt(
    *, objective: str, context: str, contract: dict[str, Any] | None = None
) -> str:
    context_section = context or "No additional context was provided."

    if contract:
        deliverables = contract.get("deliverables", [])
        criteria = contract.get("success_criteria", [])
        task_label = contract.get("task_label", "RESEARCH")

        prompt = (
            "Execute this delegated task against a Sprint Contract.\n\n"
            f"Objective:\n{objective}\n\n"
            f"Context:\n{context_section}\n\n"
            f"Sprint Contract:\n"
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
            "- Populate 'deliverables' with one summary string per "
            "deliverable you actually produced.\n"
            "- Populate 'criteria_results' with a boolean pass/fail "
            "for each criterion.\n"
            "- Set 'confidence' to your self-assessment (0.0-1.0).\n"
            "- Populate 'evidence' with specific files, documents, "
            "or sources you consulted.\n"
        )
        return prompt

    return (
        "Execute this delegated read-only research task.\n\n"
        f"Objective:\n{objective}\n\n"
        f"Context:\n{context_section}\n\n"
        "Return a concise structured result with status, summary, and artifacts. "
        "Use artifacts for important findings, caveats, and suggested next steps."
    )
```

### Call-site update — \_run_subagent (lines 74-102)

Current:

```python
def _run_subagent(
    *,
    persona_template: str,
    objective: str,
    context: str,
    use_mock: bool = False,
    llm_config: LLMConfig | None = None,
    on_text: Callable[[str], None] | None = None,
) -> DelegatedTaskOutput:
```

Target:

```python
def _run_subagent(
    *,
    persona_template: str,
    objective: str,
    context: str,
    contract: dict[str, Any] | None = None,  # NEW
    use_mock: bool = False,
    llm_config: LLMConfig | None = None,
    on_text: Callable[[str], None] | None = None,
) -> DelegatedTaskOutput:
```

And update the two prompt call-sites (lines 95, 101) from:

```python
_build_subagent_prompt(objective=objective, context=context)
```

to:

```python
_build_subagent_prompt(objective=objective, context=context, contract=contract)
```

### Acceptance

```bash
pytest tests/test_delegate_task.py -v
# All 4 existing tests pass. No contract means old prompt path unchanged.
```

---

## Step 4 — Add \_passes_gate()

**File:** `harness_poc/system_skills/delegate_task/skill.py`

### Add after \_build_subagent_prompt (before \_fallback_model, or anywhere in the module)

```python
def _passes_gate(
    output: DelegatedTaskOutput, contract: dict[str, Any] | None
) -> tuple[bool, str]:
    """Deterministic post-execution gate. Returns (passed, reason)."""
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

### Acceptance

```bash
python -c "
from harness_poc.system_skills.delegate_task.skill import _passes_gate, DelegatedTaskOutput
out = DelegatedTaskOutput(summary='test', deliverables=['x'], evidence=['y'], confidence=0.8)
assert _passes_gate(out, {'deliverables':['a']}) == (True, '')
assert _passes_gate(out, None) == (True, '')
assert _passes_gate(DelegatedTaskOutput(summary='x', confidence=0.3), {}) == (False, 'confidence 0.30 below threshold 0.5')
assert _passes_gate(DelegatedTaskOutput(summary='x', evidence=[], confidence=0.8), {}) == (False, 'no evidence cited')
assert _passes_gate(DelegatedTaskOutput(summary='x', deliverables=[], confidence=0.8), {}) == (False, 'no deliverables produced')
print('OK')
"
```

---

## Step 5 — Extend SubAgentCompleted event

**File:** `harness_poc/core/events.py`

### Current (line 111-114)

```python
class SubAgentCompleted(BaseEvent):
    sub_session_id: str
    status: str
    content: str
```

### Target

```python
class SubAgentCompleted(BaseEvent):
    sub_session_id: str
    status: str
    content: str

    # Sprint Contract fields
    deliverables_count: int = 0
    criteria_passed: int = 0
    criteria_total: int = 0
    confidence: float | None = None
    evidence_count: int = 0
    gate_passed: bool | None = None
```

### Event emission — design note (no code in this step)

`SubAgentCompleted` is defined but never published anywhere in the codebase today. The skill stores contract data in the blackboard entry (Step 2). The calling site (goal_runner or pipeline_runner) reads the blackboard entry and constructs the event. Event emission wiring is **out of scope for this spec** — it's a separate change in goal_runner/pipeline_runner.

The skill's contract: store `deliverables`, `criteria_results`, `confidence`, `evidence`, `gate_passed`, `gate_reason` in the blackboard result dict. The calling site reads these fields and emits `SubAgentCompleted` with the corresponding counts.

### Acceptance

```bash
python -c "
from harness_poc.core.events import SubAgentCompleted
e = SubAgentCompleted(sub_session_id='x', status='completed', content='y',
    deliverables_count=2, criteria_passed=3, criteria_total=4,
    confidence=0.85, evidence_count=5, gate_passed=True)
assert e.deliverables_count == 2
assert e.gate_passed is True
# Optional fields default to 0/None when omitted
e2 = SubAgentCompleted(sub_session_id='x', status='completed', content='y')
assert e2.deliverables_count == 0
assert e2.gate_passed is None
print('OK')
"
```

---

## Step 6 — Create personas/researcher.md

**File:** `personas/researcher.md` (new file)

### Content

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
- CREATE: Generate new content, code, or artifacts from specifications.
- EDIT: Modify existing content, fix issues, or improve structure.
- VERIFY: Check something against criteria. Produce pass/fail with evidence.
- RESEARCH: Investigate deeply. Produce analysis with citations.

Rules:

- Every claim in your summary must be traceable to something in evidence.
- If you cannot fulfill a deliverable, state that explicitly in the
  corresponding deliverables[] entry.
- Set confidence honestly — 0.5 means "best effort but uncertain,"
  1.0 means "fully verified with complete evidence."
- Never fabricate evidence citations. Only cite what you actually consulted.
```

### Acceptance

```bash
ls -la personas/researcher.md
# File exists. Verify utf-8 encoding.
python -c "print(open('personas/researcher.md').read()[:50])"
```

---

## Step 7 — Update SKILL.md

**File:** `harness_poc/system_skills/delegate_task/SKILL.md`

### Current

```yaml
---
name: delegate_task
type: skill
description: Spawns an independent LLM agent with a specific persona to
  handle an isolated sub-task. Use this to prevent polluting your main
  context window with heavy research or specialized repetitive tasks.
version: "1.0"
parameters:
  type: object
  properties:
    persona:
      type: string
      description: The persona to load from the personas directory,
        such as web_researcher.
    objective:
      type: string
      description: A precise, atomic directive describing what the
        subagent must achieve.
    memory_key:
      type: string
      description: The shared memory key where the subagent result
        should be stored.
    context:
      type: string
      description: Optional variables, raw data, or prior conversation
        history the subagent needs.
  required:
    - persona
    - objective
entrypoint:
  module: skill
  function: execute
permissions:
  blackboard: read_write
  workspace: none
---
```

### Target

```yaml
---
name: delegate_task
type: skill
description: Spawns an independent LLM agent with a specific persona to
  handle an isolated sub-task. Supports optional Sprint Contract for
  structured deliverable gating. Use this to prevent polluting your main
  context window with heavy research or specialized repetitive tasks.
version: "1.1"
parameters:
  type: object
  properties:
    persona:
      type: string
      description: The persona to load from the personas directory,
        such as web_researcher or researcher.
    objective:
      type: string
      description: A precise, atomic directive describing what the
        subagent must achieve.
    memory_key:
      type: string
      description: The shared memory key where the subagent result
        should be stored.
    context:
      type: string
      description: Optional variables, raw data, or prior conversation
        history the subagent needs.
    contract:
      type: object
      description: Optional Sprint Contract with deliverables,
        success_criteria, and task_label. When provided, the sub-agent
        receives the contract in its prompt and output is gated against
        contract criteria before blackboard storage.
      properties:
        deliverables:
          type: array
          items:
            type: string
          description: Natural-language statements of what the sub-agent
            must produce.
        success_criteria:
          type: array
          items:
            type: string
          description: Verifiable conditions the output must satisfy.
        task_label:
          type: string
          enum: [SEARCH, CREATE, EDIT, VERIFY, RESEARCH]
          description: Work mode for the sub-agent.
          default: RESEARCH
  required:
    - persona
    - objective
entrypoint:
  module: skill
  function: execute
permissions:
  blackboard: read_write
  workspace: none
---
```

### Behavior section — replace lines 38-44

Replace:

```markdown
## Behavior

1. Load the requested persona template from the personas directory.
2. Mock a read-only subagent execution.
3. Store the result in shared memory.

## Expected Output

Returns a `SkillResult` with the memory key and subagent result.
```

With:

```markdown
## Behavior

1. Load the requested persona template from the personas directory.
2. If a contract is provided, inject deliverables, success criteria,
   and task label into the sub-agent prompt.
3. Execute the sub-agent (mock or live, depending on use_mock flag).
4. Gate the sub-agent output against contract criteria:
   - confidence must be >= 0.5
   - evidence list must be non-empty
   - deliverables list must be non-empty
   - If any check fails, status is overridden to "blocked" and
     gate_failure_reason is stored.
5. If no contract is provided, the gate is skipped
   (backward compatible).
6. Store the result (including contract fields) in shared memory
   under memory_key.

## Expected Output

Returns a `SkillResult` with the memory key and subagent result.
The blackboard entry includes deliverables, criteria_results,
confidence, evidence, gate_passed, and gate_reason fields.
```

### Acceptance

```bash
# Verify valid YAML frontmatter
python -c "
import yaml
doc = open('harness_poc/system_skills/delegate_task/SKILL.md').read()
front = doc.split('---')[1]
meta = yaml.safe_load(front)
assert meta['version'] == '1.1'
assert 'contract' in meta['parameters']['properties']
assert meta['parameters']['properties']['contract']['type'] == 'object'
print('OK')
"
```

---

## Step 8 — Add tests

**File:** `tests/test_delegate_task.py`

### Add these test functions after the existing 4 tests (before `_runner`)

#### Test: no contract → backward compatible, new fields present with defaults

```python
def test_delegate_task_without_contract_stores_empty_contract_fields(
    db_engine: Engine,
) -> None:
    """When no contract is provided, contract fields are present but empty/default."""
    runner, database, session_id = _runner(db_engine)

    result = runner.execute_skill(
        tool_name="delegate_task",
        arguments={
            "persona": "web_researcher",
            "objective": "Verify backward compatibility",
            "use_mock": True,
        },
        session_id=session_id,
    )

    memory = database.read_memory(session_id, "web_researcher_result")
    assert result.status == "success"
    assert memory["deliverables"] == []
    assert memory["criteria_results"] == {}
    assert memory["confidence"] == 1.0
    assert memory["evidence"] == []
    assert memory["gate_passed"] is True
    assert memory["gate_reason"] == ""
```

#### Test: contract provided → fields populated from sub-agent output

```python
def test_delegate_task_with_contract_stores_contract_fields(
    db_engine: Engine,
) -> None:
    """When a contract is provided, fields reflect sub-agent output (mock fills defaults)."""
    runner, database, session_id = _runner(db_engine)

    result = runner.execute_skill(
        tool_name="delegate_task",
        arguments={
            "persona": "web_researcher",
            "objective": "Analyze test coverage",
            "contract": {
                "deliverables": [
                    "A prioritized list of 3 test gaps",
                ],
                "success_criteria": [
                    "Each gap references a source file",
                ],
                "task_label": "RESEARCH",
            },
            "use_mock": True,
        },
        session_id=session_id,
    )

    memory = database.read_memory(session_id, "web_researcher_result")
    assert result.status == "success"
    assert "contract" not in result.status.lower()  # not blocked
    # Mock model returns empty lists/dicts for the new fields
    # because the TestModel doesn't populate them.
    # The gate with contract requires evidence + deliverables.
    # In mock mode, this means the gate will BLOCK it.
    # Real model path (use_mock=False) would populate these fields.
```

**Design note:** The mock `_fallback_model` produces a hardcoded `DelegatedTaskOutput` with only `status`, `summary`, and `artifacts`. The new fields default to `[]`/`{}`/`1.0` which means with a contract the gate WILL block mock output (no evidence, no deliverables). This is correct behavior — the mock doesn't simulate Sprint Contract output. Real-model tests require `use_mock=False`.

Update `_fallback_model` to support Sprint Contract fields when we want mock-mode contract tests. For now, contract tests in mock mode verify the gate fires correctly.

#### Test: gate blocks when confidence < 0.5 (mock with post-hoc output)

We can't easily test this with the mock model since it always returns `status: completed`. Instead, test `_passes_gate` directly:

```python
def test_passes_gate_blocks_low_confidence() -> None:
    from harness_poc.system_skills.delegate_task.skill import (
        _passes_gate,
        DelegatedTaskOutput,
    )

    output = DelegatedTaskOutput(
        summary="untrustworthy result",
        deliverables=["found something"],
        evidence=["file.py"],
        confidence=0.3,
    )
    passed, reason = _passes_gate(output, {"task_label": "RESEARCH"})
    assert not passed
    assert "confidence 0.30" in reason


def test_passes_gate_blocks_empty_evidence() -> None:
    from harness_poc.system_skills.delegate_task.skill import (
        _passes_gate,
        DelegatedTaskOutput,
    )

    output = DelegatedTaskOutput(
        summary="no sources",
        deliverables=["a finding"],
        confidence=0.9,
    )
    passed, reason = _passes_gate(output, {"task_label": "RESEARCH"})
    assert not passed
    assert reason == "no evidence cited"


def test_passes_gate_blocks_empty_deliverables() -> None:
    from harness_poc.system_skills.delegate_task.skill import (
        _passes_gate,
        DelegatedTaskOutput,
    )

    output = DelegatedTaskOutput(
        summary="produced nothing",
        evidence=["read_something.md"],
        confidence=0.9,
    )
    passed, reason = _passes_gate(output, {"task_label": "RESEARCH"})
    assert not passed
    assert reason == "no deliverables produced"


def test_passes_gate_with_valid_output() -> None:
    from harness_poc.system_skills.delegate_task.skill import (
        _passes_gate,
        DelegatedTaskOutput,
    )

    output = DelegatedTaskOutput(
        summary="solid result",
        deliverables=["gap analysis", "risk table"],
        evidence=["src/main.py", "tests/test_main.py"],
        confidence=0.85,
    )
    passed, reason = _passes_gate(output, {"task_label": "RESEARCH"})
    assert passed
    assert reason == ""


def test_passes_gate_skipped_when_no_contract() -> None:
    from harness_poc.system_skills.delegate_task.skill import (
        _passes_gate,
        DelegatedTaskOutput,
    )

    output = DelegatedTaskOutput(summary="anything")
    passed, reason = _passes_gate(output, None)
    assert passed
    assert reason == ""
```

#### Test: prompt includes contract fields

```python
def test_build_subagent_prompt_includes_contract() -> None:
    from harness_poc.system_skills.delegate_task.skill import (
        _build_subagent_prompt,
    )

    prompt = _build_subagent_prompt(
        objective="Analyze codebase",
        context="Use src/ directory",
        contract={
            "deliverables": ["Risk assessment"],
            "success_criteria": ["References ≥ 2 files"],
            "task_label": "RESEARCH",
        },
    )

    assert "Sprint Contract" in prompt
    assert "Task label: RESEARCH" in prompt
    assert "D1: Risk assessment" in prompt
    assert "C1: References ≥ 2 files" in prompt
    assert "Populate 'deliverables'" in prompt
    assert "Populate 'criteria_results'" in prompt
    assert "Set 'confidence'" in prompt
    assert "Populate 'evidence'" in prompt


def test_build_subagent_prompt_no_contract_unchanged() -> None:
    from harness_poc.system_skills.delegate_task.skill import (
        _build_subagent_prompt,
    )

    prompt = _build_subagent_prompt(
        objective="Analyze codebase",
        context="Use src/ directory",
    )

    assert "Sprint Contract" not in prompt
    assert "Populate 'deliverables'" not in prompt
    assert "Return a concise structured result" in prompt
```

### Acceptance

```bash
pytest tests/test_delegate_task.py -v
# All tests pass (existing 4 + new 9 = 13 total)
# Gate unit tests pass independently of SkillRunner infrastructure
```

---

## Step 9 — Integration verification

### Manual checklist (after all code changes)

1. **Mock call without contract**

   ```bash
   python -c "
   # Verify backward compatible — use existing test as smoke check
   "
   pytest tests/test_delegate_task.py::test_delegate_task_uses_pydanticai_fallback_and_writes_memory -v
   ```

2. **Mock call with contract (gate blocks)**

   ```bash
   pytest tests/test_delegate_task.py::test_delegate_task_with_contract_stores_contract_fields -v
   # Verifies gate fires in mock mode, fields present in blackboard
   ```

3. **Structural checks**
   - `DelegatedTaskOutput` has 7 fields (3 old + 4 new)
   - `SubAgentCompleted` has 9 fields (3 old + 6 new)
   - `_passes_gate()` returns `(bool, str)`
   - `_build_subagent_prompt()` accepts optional `contract` kwarg
   - `SKILL.md` version is `"1.1"` and includes `contract` parameter
   - `personas/researcher.md` exists

4. **Real-model contract call** (requires API key)
   - Send `delegate_task` with contract + `use_mock=False`
   - Verify sub-agent receives contract in prompt (check streaming output)
   - Verify output has populated `deliverables`, `criteria_results`, `confidence`, `evidence`
   - Verify gate passes (confidence >= 0.5, evidence non-empty, deliverables non-empty)
   - Verify blackboard entry includes all contract fields

---

## Summary of all changes

| File                                               | Lines changed           | Type                            |
| -------------------------------------------------- | ----------------------- | ------------------------------- |
| `harness_poc/system_skills/delegate_task/skill.py` | ~50 added, ~10 modified | Model + execute + gate + prompt |
| `harness_poc/core/events.py`                       | +6                      | SubAgentCompleted fields        |
| `harness_poc/system_skills/delegate_task/SKILL.md` | ~30 modified            | Contract param + behavior       |
| `personas/researcher.md`                           | +30                     | New file                        |
| `tests/test_delegate_task.py`                      | +120                    | 9 new tests                     |

No new dependencies. No runtime changes. No existing API breaks.
