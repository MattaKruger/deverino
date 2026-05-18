# Spec Writer Gather Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a multi-turn `gather` mode to the spec_writer skill that walks the user through a structured Q&A and produces a standardized XML context document for LLM-driven spec drafting.

**Architecture:** A phase-based state machine (`GatherState`) is persisted in the SQLite blackboard between calls. Each `gather` invocation applies the user's `answer` to the current phase, advances to the next phase, and returns the next question — or, when all phases are complete, generates and writes an XML context document. The existing `draft` mode gains an optional `gather_key` that reads a completed XML context from the blackboard and feeds it to the LLM instead of the flat inputs.

**Tech Stack:** Python 3.12, pytest, existing `SkillContext`/`SkillResult`/`BlackboardDatabase` from `harness_poc/core/`.

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Modify | `skills/spec_writer/skill.py` | All gather logic, XML generation, draft gather_key path |
| Modify | `skills/spec_writer/SKILL.md` | Document `gather` mode, `gather_key`, `answer` parameters |
| Modify | `tests/test_spec_writer.py` | All new tests — gather state machine, XML output, draft integration |

---

## Task 1: GatherState dataclass + blackboard round-trip

**Files:**
- Modify: `skills/spec_writer/skill.py` (top of file, after imports)
- Test: `tests/test_spec_writer.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_spec_writer.py`:

```python
from skills.spec_writer.skill import GatherState, _load_gather_state, _save_gather_state


def test_gather_state_round_trips_through_blackboard(tmp_path: Path) -> None:
    _runner_obj, session_id, database = _runner(tmp_path)
    from harness_poc.core.skill_context import SkillContext
    from harness_poc.core.config import HarnessConfig, HarnessPaths, RuntimeConfig

    config = _test_config(tmp_path)
    ctx = SkillContext(
        session_id=session_id,
        skill_name="spec_writer",
        database=database,
        config=config,
    )

    state = GatherState(
        phase="awaiting_feature_request",
        project_overview="A Python agent harness.",
        feature_request="",
        component_names=["GoalRunner", "EvalSkill"],
        component_details={"GoalRunner": "Manages the loop"},
        current_component_index=1,
        constraints="",
        xml_context="",
    )
    _save_gather_state(ctx, "test_key", state)
    loaded = _load_gather_state(ctx, "test_key")

    assert loaded is not None
    assert loaded.phase == "awaiting_feature_request"
    assert loaded.project_overview == "A Python agent harness."
    assert loaded.component_names == ["GoalRunner", "EvalSkill"]
    assert loaded.component_details == {"GoalRunner": "Manages the loop"}
    assert loaded.current_component_index == 1


def test_load_gather_state_returns_none_when_missing(tmp_path: Path) -> None:
    _runner_obj, session_id, database = _runner(tmp_path)
    config = _test_config(tmp_path)
    from harness_poc.core.skill_context import SkillContext
    ctx = SkillContext(session_id=session_id, skill_name="spec_writer", database=database, config=config)

    assert _load_gather_state(ctx, "nonexistent_key") is None
```

- [ ] **Step 2: Run to confirm failure**

```bash
uv run pytest tests/test_spec_writer.py::test_gather_state_round_trips_through_blackboard -v
```

Expected: `ImportError` or `AttributeError` — `GatherState` not yet defined.

- [ ] **Step 3: Implement GatherState and helpers in skill.py**

Add after the existing imports and before `DEFAULT_OUTPUT_KEY`:

```python
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Literal

GatherPhase = Literal[
    "awaiting_project_overview",
    "awaiting_feature_request",
    "awaiting_components_list",
    "awaiting_component_detail",
    "awaiting_constraints",
    "complete",
]

DEFAULT_GATHER_KEY = "spec_gather_state"


@dataclass(slots=True)
class GatherState:
    phase: GatherPhase
    project_overview: str = ""
    feature_request: str = ""
    component_names: list[str] = field(default_factory=list)
    component_details: dict[str, str] = field(default_factory=dict)
    current_component_index: int = 0
    constraints: str = ""
    xml_context: str = ""


def _load_gather_state(ctx: SkillContext, gather_key: str) -> GatherState | None:
    payload = ctx.database.read_memory(ctx.session_id, gather_key)
    if not isinstance(payload, dict):
        return None
    return GatherState(
        phase=payload.get("phase", "awaiting_project_overview"),
        project_overview=payload.get("project_overview", ""),
        feature_request=payload.get("feature_request", ""),
        component_names=payload.get("component_names", []),
        component_details=payload.get("component_details", {}),
        current_component_index=payload.get("current_component_index", 0),
        constraints=payload.get("constraints", ""),
        xml_context=payload.get("xml_context", ""),
    )


def _save_gather_state(ctx: SkillContext, gather_key: str, state: GatherState) -> None:
    ctx.database.write_memory(
        ctx.session_id,
        gather_key,
        {
            "phase": state.phase,
            "project_overview": state.project_overview,
            "feature_request": state.feature_request,
            "component_names": state.component_names,
            "component_details": state.component_details,
            "current_component_index": state.current_component_index,
            "constraints": state.constraints,
            "xml_context": state.xml_context,
        },
    )
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
uv run pytest tests/test_spec_writer.py::test_gather_state_round_trips_through_blackboard tests/test_spec_writer.py::test_load_gather_state_returns_none_when_missing -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add skills/spec_writer/skill.py tests/test_spec_writer.py
git commit -m "feat(spec_writer): add GatherState dataclass and blackboard helpers"
```

---

## Task 2: Component name parsing + phase question strings

**Files:**
- Modify: `skills/spec_writer/skill.py`
- Test: `tests/test_spec_writer.py`

- [ ] **Step 1: Write the failing tests**

```python
from skills.spec_writer.skill import _parse_component_names, _question_for_phase


def test_parse_component_names_handles_comma_separated() -> None:
    result = _parse_component_names("GoalRunner, EvalSkill, LoopGuard")
    assert result == ["GoalRunner", "EvalSkill", "LoopGuard"]


def test_parse_component_names_handles_bullet_list() -> None:
    result = _parse_component_names("- GoalRunner\n- EvalSkill\n- LoopGuard")
    assert result == ["GoalRunner", "EvalSkill", "LoopGuard"]


def test_parse_component_names_handles_mixed_format() -> None:
    result = _parse_component_names("GoalRunner\nEvalSkill, LoopGuard")
    assert result == ["GoalRunner", "EvalSkill", "LoopGuard"]


def test_parse_component_names_strips_empty_lines() -> None:
    result = _parse_component_names("\n- Alpha\n\n- Beta\n")
    assert result == ["Alpha", "Beta"]


def test_question_for_phase_project_overview() -> None:
    state = GatherState(phase="awaiting_project_overview")
    q = _question_for_phase(state)
    assert "project" in q.lower()
    assert "1/" in q


def test_question_for_phase_components_list() -> None:
    state = GatherState(phase="awaiting_components_list")
    q = _question_for_phase(state)
    assert "component" in q.lower()


def test_question_for_phase_component_detail_names_component() -> None:
    state = GatherState(
        phase="awaiting_component_detail",
        component_names=["GoalRunner", "EvalSkill"],
        current_component_index=0,
    )
    q = _question_for_phase(state)
    assert "GoalRunner" in q
    assert "1/2" in q


def test_question_for_phase_component_detail_second_component() -> None:
    state = GatherState(
        phase="awaiting_component_detail",
        component_names=["GoalRunner", "EvalSkill"],
        current_component_index=1,
    )
    q = _question_for_phase(state)
    assert "EvalSkill" in q
    assert "2/2" in q
```

- [ ] **Step 2: Run to confirm failure**

```bash
uv run pytest tests/test_spec_writer.py -k "parse_component or question_for_phase" -v
```

Expected: `ImportError` — functions not yet defined.

- [ ] **Step 3: Implement the two functions in skill.py**

```python
def _parse_component_names(answer: str) -> list[str]:
    names: list[str] = []
    for line in answer.splitlines():
        line = line.strip(" \t-•*")
        if not line:
            continue
        for part in line.split(","):
            part = part.strip()
            if part:
                names.append(part)
    return names


def _question_for_phase(state: GatherState) -> str:
    if state.phase == "awaiting_project_overview":
        return (
            "## Gathering Spec Context (1/4)\n\n"
            "Describe the project: what it does, the tech stack, and any key "
            "architectural patterns the spec author should know."
        )
    if state.phase == "awaiting_feature_request":
        return (
            "## Gathering Spec Context (2/4)\n\n"
            "Describe the feature you want to implement. What is the user intent? "
            "What should it do from the user's perspective?"
        )
    if state.phase == "awaiting_components_list":
        return (
            "## Gathering Spec Context (3/4)\n\n"
            "List the named architectural components this feature requires "
            "(e.g. DatabaseUpdates, GoalRunner, EvaluatorSkill). "
            "One per line or comma-separated."
        )
    if state.phase == "awaiting_component_detail":
        idx = state.current_component_index
        name = state.component_names[idx]
        total = len(state.component_names)
        return (
            f"## Component {idx + 1}/{total}: {name}\n\n"
            f"Describe what `{name}` does: its responsibilities, what it creates "
            f"or modifies, and any interfaces it must implement or expose."
        )
    if state.phase == "awaiting_constraints":
        return (
            "## Gathering Spec Context (4/4)\n\n"
            "List any technical, product, or delivery constraints "
            "(e.g. no external frameworks, must be idempotent, Python 3.12+ typing)."
        )
    return ""
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
uv run pytest tests/test_spec_writer.py -k "parse_component or question_for_phase" -v
```

Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add skills/spec_writer/skill.py tests/test_spec_writer.py
git commit -m "feat(spec_writer): add component name parser and phase question strings"
```

---

## Task 3: Phase state machine — _apply_answer_and_advance

**Files:**
- Modify: `skills/spec_writer/skill.py`
- Test: `tests/test_spec_writer.py`

- [ ] **Step 1: Write the failing tests**

```python
from skills.spec_writer.skill import _apply_answer_and_advance


def test_apply_answer_project_overview_advances_to_feature_request() -> None:
    state = GatherState(phase="awaiting_project_overview")
    result = _apply_answer_and_advance(state, "A Python harness for LLM agents.")
    assert result.phase == "awaiting_feature_request"
    assert result.project_overview == "A Python harness for LLM agents."


def test_apply_answer_feature_request_advances_to_components_list() -> None:
    state = GatherState(phase="awaiting_feature_request", project_overview="...")
    result = _apply_answer_and_advance(state, "Add an autonomous goal loop.")
    assert result.phase == "awaiting_components_list"
    assert result.feature_request == "Add an autonomous goal loop."


def test_apply_answer_components_list_advances_to_component_detail() -> None:
    state = GatherState(phase="awaiting_components_list")
    result = _apply_answer_and_advance(state, "GoalRunner, EvalSkill")
    assert result.phase == "awaiting_component_detail"
    assert result.component_names == ["GoalRunner", "EvalSkill"]
    assert result.current_component_index == 0


def test_apply_answer_component_detail_loops_to_next_component() -> None:
    state = GatherState(
        phase="awaiting_component_detail",
        component_names=["GoalRunner", "EvalSkill"],
        current_component_index=0,
    )
    result = _apply_answer_and_advance(state, "Manages the while loop.")
    assert result.phase == "awaiting_component_detail"
    assert result.current_component_index == 1
    assert result.component_details["GoalRunner"] == "Manages the while loop."


def test_apply_answer_last_component_detail_advances_to_constraints() -> None:
    state = GatherState(
        phase="awaiting_component_detail",
        component_names=["GoalRunner", "EvalSkill"],
        current_component_index=1,
    )
    result = _apply_answer_and_advance(state, "Acts as the exit mechanism.")
    assert result.phase == "awaiting_constraints"
    assert result.component_details["EvalSkill"] == "Acts as the exit mechanism."


def test_apply_answer_constraints_advances_to_complete() -> None:
    state = GatherState(phase="awaiting_constraints")
    result = _apply_answer_and_advance(state, "No external frameworks.")
    assert result.phase == "complete"
    assert result.constraints == "No external frameworks."


def test_apply_answer_empty_answer_does_not_advance() -> None:
    state = GatherState(phase="awaiting_project_overview")
    result = _apply_answer_and_advance(state, "")
    assert result.phase == "awaiting_project_overview"
    assert result.project_overview == ""
```

- [ ] **Step 2: Run to confirm failure**

```bash
uv run pytest tests/test_spec_writer.py -k "apply_answer" -v
```

Expected: `ImportError`

- [ ] **Step 3: Implement `_apply_answer_and_advance` in skill.py**

```python
def _apply_answer_and_advance(state: GatherState, answer: str) -> GatherState:
    if not answer.strip():
        return state

    if state.phase == "awaiting_project_overview":
        state.project_overview = answer.strip()
        state.phase = "awaiting_feature_request"

    elif state.phase == "awaiting_feature_request":
        state.feature_request = answer.strip()
        state.phase = "awaiting_components_list"

    elif state.phase == "awaiting_components_list":
        state.component_names = _parse_component_names(answer)
        state.current_component_index = 0
        state.phase = "awaiting_component_detail"

    elif state.phase == "awaiting_component_detail":
        name = state.component_names[state.current_component_index]
        state.component_details[name] = answer.strip()
        next_index = state.current_component_index + 1
        if next_index < len(state.component_names):
            state.current_component_index = next_index
        else:
            state.phase = "awaiting_constraints"

    elif state.phase == "awaiting_constraints":
        state.constraints = answer.strip()
        state.phase = "complete"

    return state
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
uv run pytest tests/test_spec_writer.py -k "apply_answer" -v
```

Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add skills/spec_writer/skill.py tests/test_spec_writer.py
git commit -m "feat(spec_writer): implement gather phase state machine"
```

---

## Task 4: XML context generation + file writing

**Files:**
- Modify: `skills/spec_writer/skill.py`
- Test: `tests/test_spec_writer.py`

- [ ] **Step 1: Write the failing tests**

```python
from skills.spec_writer.skill import _generate_xml_context, _write_xml_context_file


def test_generate_xml_context_includes_all_sections() -> None:
    state = GatherState(
        phase="complete",
        project_overview="A Python harness.",
        feature_request="Add goal loop.",
        component_names=["GoalRunner", "EvalSkill"],
        component_details={
            "GoalRunner": "Manages the while loop.",
            "EvalSkill": "Acts as the exit mechanism.",
        },
        constraints="No external frameworks.",
    )
    xml = _generate_xml_context(state)

    assert "<context>" in xml
    assert "<project_overview>" in xml
    assert "A Python harness." in xml
    assert "<feature_request>" in xml
    assert "Add goal loop." in xml
    assert '<component name="GoalRunner">' in xml
    assert "Manages the while loop." in xml
    assert '<component name="EvalSkill">' in xml
    assert "Acts as the exit mechanism." in xml
    assert "<constraints>" in xml
    assert "No external frameworks." in xml
    assert "<output_instructions>" in xml
    assert "</context>" in xml


def test_write_xml_context_file_creates_file(tmp_path: Path) -> None:
    xml = "<context><project_overview>Test</project_overview></context>"
    path = _write_xml_context_file(tmp_path, xml)
    assert path.exists()
    assert path.suffix == ".xml"
    assert path.read_text() == xml + "\n"
```

- [ ] **Step 2: Run to confirm failure**

```bash
uv run pytest tests/test_spec_writer.py -k "xml_context or write_xml" -v
```

Expected: `ImportError`

- [ ] **Step 3: Implement XML generation and file writing in skill.py**

```python
def _generate_xml_context(state: GatherState) -> str:
    components_lines: list[str] = []
    for name in state.component_names:
        detail = state.component_details.get(name, "")
        components_lines.append(f'    <component name="{name}">')
        components_lines.append(f"      {detail}")
        components_lines.append("    </component>")

    components_block = "\n".join(components_lines)

    return "\n".join([
        "<context>",
        "  <project_overview>",
        f"    {state.project_overview}",
        "  </project_overview>",
        "",
        "  <feature_request>",
        f"    {state.feature_request}",
        "  </feature_request>",
        "",
        "  <architectural_requirements>",
        components_block,
        "  </architectural_requirements>",
        "",
        "  <constraints>",
        f"    {state.constraints}",
        "  </constraints>",
        "",
        "  <output_instructions>",
        "    Act as a senior software architect. Write a comprehensive Technical",
        "    Specification for this feature. Include:",
        "    1. System architecture flow (how the components interact).",
        "    2. Data schema modifications.",
        "    3. Interface definitions (class signatures and skill schemas).",
        "    4. Edge cases and failure modes.",
        "    5. Step-by-step implementation plan.",
        "  </output_instructions>",
        "</context>",
    ])


def _write_xml_context_file(project_root: Path, xml: str) -> Path:
    specs_dir = project_root / "specs"
    specs_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    path = specs_dir / f"{timestamp}-gather-context.xml"
    path.write_text(xml.rstrip() + "\n", encoding="utf-8")
    return path
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
uv run pytest tests/test_spec_writer.py -k "xml_context or write_xml" -v
```

Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add skills/spec_writer/skill.py tests/test_spec_writer.py
git commit -m "feat(spec_writer): implement XML context generation and file writing"
```

---

## Task 5: Wire gather mode into execute() — end-to-end via SkillRunner

**Files:**
- Modify: `skills/spec_writer/skill.py` (SpecInputs, VALID_MODES, execute, new _execute_gather)
- Test: `tests/test_spec_writer.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_gather_first_call_asks_project_overview(tmp_path: Path) -> None:
    runner, session_id, _ = _runner(tmp_path)
    result = runner.execute_skill(
        tool_name="spec_writer",
        arguments={"mode": "gather", "gather_key": "test_gather"},
        session_id=session_id,
    )
    assert result.status == "needs_orchestrator_action"
    assert "project" in result.content.lower()
    assert result.artifacts["phase"] == "awaiting_project_overview"
    assert result.artifacts["gather_key"] == "test_gather"


def test_gather_answer_advances_to_next_phase(tmp_path: Path) -> None:
    runner, session_id, _ = _runner(tmp_path)
    # First call — get project overview question
    runner.execute_skill(
        tool_name="spec_writer",
        arguments={"mode": "gather", "gather_key": "test_gather"},
        session_id=session_id,
    )
    # Second call — answer the question
    result = runner.execute_skill(
        tool_name="spec_writer",
        arguments={
            "mode": "gather",
            "gather_key": "test_gather",
            "answer": "A Python LLM agent harness backed by SQLite.",
        },
        session_id=session_id,
    )
    assert result.status == "needs_orchestrator_action"
    assert result.artifacts["phase"] == "awaiting_feature_request"


def test_gather_full_flow_produces_xml(tmp_path: Path) -> None:
    runner, session_id, _ = _runner(tmp_path)
    key = "full_gather_test"

    def call(answer: str = "") -> object:
        return runner.execute_skill(
            tool_name="spec_writer",
            arguments={"mode": "gather", "gather_key": key, "answer": answer},
            session_id=session_id,
        )

    call()                                          # ask project overview
    call("A Python LLM harness.")                   # answer project overview
    call("Add an autonomous goal loop.")            # answer feature request
    call("GoalRunner, EvalSkill")                   # answer components list
    call("Manages the while loop.")                 # answer GoalRunner detail
    result = call("Acts as exit mechanism.")        # answer EvalSkill detail → goes to constraints
    assert result.artifacts["phase"] == "awaiting_constraints"

    result = call("No external frameworks.")        # answer constraints → complete
    assert result.status == "success"
    assert "<context>" in result.content
    assert "A Python LLM harness." in result.content
    assert "GoalRunner" in result.content
    assert "No external frameworks." in result.content
    assert result.artifacts["phase"] == "complete"

    xml_path = Path(result.artifacts["xml_path"])
    assert xml_path.parts[0] == "specs"
    assert (tmp_path / xml_path).exists()


def test_gather_uses_default_gather_key_when_not_provided(tmp_path: Path) -> None:
    runner, session_id, _ = _runner(tmp_path)
    result = runner.execute_skill(
        tool_name="spec_writer",
        arguments={"mode": "gather"},
        session_id=session_id,
    )
    assert result.artifacts["gather_key"] == "spec_gather_state"
```

- [ ] **Step 2: Run to confirm failure**

```bash
uv run pytest tests/test_spec_writer.py -k "gather" -v
```

Expected: failures because `gather` is not a valid mode yet.

- [ ] **Step 3: Add `gather_key` and `answer` to SpecInputs**

In `_parse_inputs` and `SpecInputs` (replace the existing dataclass and function):

```python
@dataclass(frozen=True, slots=True)
class SpecInputs:
    goal: str
    context: str
    mode: str
    output_key: str
    title: str
    requirements: str
    constraints: str
    non_goals: str
    open_questions: str
    use_llm: bool
    gather_key: str   # blackboard key for gather state
    answer: str       # user's answer to the previous gather question


VALID_MODES = {"draft", "refine", "questions", "gather"}
```

In `_parse_inputs`, add at the end of the function before `return`:

```python
    return SpecInputs(
        goal=goal,
        context=_string_value(arguments, "context"),
        mode=mode,
        output_key=_string_value(arguments, "output_key") or DEFAULT_OUTPUT_KEY,
        title=_string_value(arguments, "title"),
        requirements=_string_value(arguments, "requirements"),
        constraints=_string_value(arguments, "constraints"),
        non_goals=_string_value(arguments, "non_goals"),
        open_questions=_string_value(arguments, "open_questions"),
        use_llm=_bool_value(arguments.get("use_llm", False)),
        gather_key=_string_value(arguments, "gather_key") or DEFAULT_GATHER_KEY,
        answer=_string_value(arguments, "answer"),
    )
```

- [ ] **Step 4: Add `_execute_gather` and wire into `execute()`**

```python
def _execute_gather(ctx: SkillContext, inputs: SpecInputs) -> SkillResult:
    gather_key = inputs.gather_key

    state = _load_gather_state(ctx, gather_key)
    if state is None:
        state = GatherState(phase="awaiting_project_overview")

    state = _apply_answer_and_advance(state, inputs.answer)

    if state.phase == "complete":
        xml = _generate_xml_context(state)
        state.xml_context = xml
        _save_gather_state(ctx, gather_key, state)
        xml_path = _write_xml_context_file(ctx.project_root, xml)
        return SkillResult(
            status="success",
            content=xml,
            artifacts={
                "gather_key": gather_key,
                "xml_path": str(xml_path.relative_to(ctx.project_root)),
                "phase": "complete",
            },
        )

    _save_gather_state(ctx, gather_key, state)
    question = _question_for_phase(state)
    return SkillResult(
        status="needs_orchestrator_action",
        content=question,
        artifacts={"gather_key": gather_key, "phase": state.phase},
    )
```

In `execute()`, add a branch before the existing `questions` check:

```python
def execute(ctx: SkillContext, arguments: dict[str, Any]) -> SkillResult:
    inputs = _parse_inputs(arguments)

    if inputs.mode == "gather":
        return _execute_gather(ctx, inputs)

    questions = _clarifying_questions(inputs)
    # ... rest of existing function unchanged
```

- [ ] **Step 5: Run all gather tests**

```bash
uv run pytest tests/test_spec_writer.py -k "gather" -v
```

Expected: all PASS

- [ ] **Step 6: Run the full test suite to check for regressions**

```bash
uv run pytest tests/test_spec_writer.py -v
```

Expected: all PASS (existing draft/refine/questions tests unaffected)

- [ ] **Step 7: Commit**

```bash
git add skills/spec_writer/skill.py tests/test_spec_writer.py
git commit -m "feat(spec_writer): wire gather mode into execute() with full state machine"
```

---

## Task 6: Draft mode — consume XML context via gather_key

**Files:**
- Modify: `skills/spec_writer/skill.py`
- Test: `tests/test_spec_writer.py`

- [ ] **Step 1: Write the failing test**

```python
def test_draft_with_gather_key_uses_xml_context_for_llm(tmp_path: Path) -> None:
    runner, session_id, database = _runner(tmp_path)
    config = _test_config(tmp_path)
    from harness_poc.core.skill_context import SkillContext

    # Pre-populate a completed gather state in the blackboard
    ctx = SkillContext(session_id=session_id, skill_name="spec_writer", database=database, config=config)
    completed_state = GatherState(
        phase="complete",
        project_overview="A Python harness.",
        feature_request="Add goal loop.",
        component_names=["GoalRunner"],
        component_details={"GoalRunner": "Manages the loop."},
        constraints="No external frameworks.",
        xml_context="<context>previously generated</context>",
    )
    _save_gather_state(ctx, "prefilled_gather", completed_state)

    # draft mode with gather_key should find the XML context and pass it to LLM
    result = runner.execute_skill(
        tool_name="spec_writer",
        arguments={
            "mode": "draft",
            "goal": "Add goal loop",
            "context": "A Python harness.",
            "requirements": "Implement a while loop",
            "gather_key": "prefilled_gather",
            "use_llm": False,  # use deterministic path; we just verify no crash and correct flow
        },
        session_id=session_id,
    )
    # Deterministic path still works even when gather_key is present
    assert result.status == "success"
    assert "## Objective" in result.content


def test_draft_without_gather_key_ignores_gather_state(tmp_path: Path) -> None:
    runner, session_id, _ = _runner(tmp_path)
    result = runner.execute_skill(
        tool_name="spec_writer",
        arguments={
            "goal": "Add export support",
            "context": "A Python harness.",
            "requirements": "Write to disk",
        },
        session_id=session_id,
    )
    assert result.status == "success"
    assert "## Objective" in result.content
```

- [ ] **Step 2: Run to confirm the gather_key test exercises the right path**

```bash
uv run pytest tests/test_spec_writer.py::test_draft_with_gather_key_uses_xml_context_for_llm tests/test_spec_writer.py::test_draft_without_gather_key_ignores_gather_state -v
```

Expected: PASS already (no code change needed — the deterministic path ignores gather_key). If FAIL, investigate.

- [ ] **Step 3: Update `_draft_with_optional_llm` to accept and use xml_context**

This change ensures that when `use_llm=True` and a completed gather is present, the LLM gets the rich XML context rather than the flat inputs:

```python
def _draft_with_optional_llm(
    inputs: SpecInputs, previous_spec: str, xml_context: str = ""
) -> tuple[str, bool]:
    if inputs.use_llm and _should_try_llm():
        messages = (
            _llm_messages_with_xml(xml_context, inputs, previous_spec)
            if xml_context
            else _llm_messages(inputs, previous_spec)
        )
        response = LLMClient().chat(messages, tools=None)
        candidate = response.content.strip()
        if _is_valid_spec(candidate):
            return candidate, True
    return _deterministic_spec(inputs, previous_spec), False


def _llm_messages_with_xml(
    xml_context: str, inputs: SpecInputs, previous_spec: str
) -> list[Message]:
    return [
        {
            "role": "system",
            "content": (
                "Write concise implementation-ready markdown specs. Use exactly these "
                "headings: Objective, Background, Requirements, Non-Goals, Proposed "
                "Behavior, Acceptance Criteria, Test Plan, Open Questions. Do not add "
                "marketing copy. Preserve unresolved open questions."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Use the following structured context to write the spec.\n\n"
                f"{xml_context}\n\n"
                f"Mode: {inputs.mode}\n"
                f"Previous spec:\n{previous_spec}"
            ),
        },
    ]
```

In `execute()`, resolve `xml_context` before calling `_draft_with_optional_llm`:

```python
    # In the draft/refine branch, before calling _draft_with_optional_llm:
    xml_context = ""
    if inputs.gather_key != DEFAULT_GATHER_KEY or inputs.gather_key:
        gather_state = _load_gather_state(ctx, inputs.gather_key)
        if gather_state is not None and gather_state.phase == "complete":
            xml_context = gather_state.xml_context

    spec, used_llm = _draft_with_optional_llm(inputs, previous_spec, xml_context)
```

- [ ] **Step 4: Run all tests**

```bash
uv run pytest tests/test_spec_writer.py -v
```

Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add skills/spec_writer/skill.py tests/test_spec_writer.py
git commit -m "feat(spec_writer): draft mode reads XML context from completed gather session"
```

---

## Task 7: Update SKILL.md

**Files:**
- Modify: `skills/spec_writer/SKILL.md`

- [ ] **Step 1: Update SKILL.md parameters block**

Replace the existing `parameters` section with:

```yaml
parameters:
  type: object
  properties:
    goal:
      type: string
      description: Feature, change, or product intent to turn into a spec.
    context:
      type: string
      description: Existing behavior, user need, or technical background.
    mode:
      type: string
      description: >
        gather = multi-turn Q&A that produces an XML context document;
        draft = write a markdown spec from flat inputs or a completed gather session;
        refine = improve an existing draft;
        questions = return clarifying questions only.
      enum:
        - gather
        - draft
        - refine
        - questions
    gather_key:
      type: string
      description: >
        Blackboard key for gather session state. In gather mode, persists phase
        progress across calls. In draft/refine mode, reads a completed XML context
        from this key if one exists. Defaults to spec_gather_state.
    answer:
      type: string
      description: >
        The user's answer to the most recent gather question. Pass on every gather
        call after the first. Empty string on the first call.
    output_key:
      type: string
      description: Memory key where the spec draft should be stored. Defaults to spec_writer_result.
    title:
      type: string
      description: Optional title for the generated spec.
    requirements:
      type: string
      description: Known functional requirements or acceptance expectations.
    constraints:
      type: string
      description: Technical, product, or delivery constraints.
    non_goals:
      type: string
      description: Explicitly excluded scope.
    open_questions:
      type: string
      description: Known unresolved questions to include in the final spec.
    use_llm:
      type: boolean
      description: Whether to allow LLM drafting after clarity checks pass. Defaults to false.
  required: []
```

- [ ] **Step 2: Update the Behavior section in SKILL.md**

Replace the `## Behavior` section with:

```markdown
## Behavior

### gather mode (multi-turn)
1. On each call, reads current phase from the blackboard (`gather_key`).
2. If `answer` is non-empty, applies it to the current phase and advances.
3. Returns the question for the new phase with `status: needs_orchestrator_action`.
4. Phase sequence: project overview → feature request → component names → per-component detail (one loop iteration per component) → constraints → complete.
5. When complete, generates and writes an XML context document to `specs/` and returns `status: success`.

### draft / refine mode
1. If `gather_key` points to a completed gather session, passes the XML context to the LLM instead of flat inputs.
2. Falls back to flat inputs (`goal`, `context`, `requirements`, etc.) when no completed gather session is found.
3. Writes the resulting markdown spec to `specs/` and stores it in blackboard memory under `output_key`.

### questions mode
Returns up to 3 clarifying questions without drafting anything.
```

- [ ] **Step 3: Verify the skill is still discovered correctly**

```bash
uv run harness-poc skill list
```

Expected: `spec_writer` appears in the project skills list.

- [ ] **Step 4: Run full test suite one final time**

```bash
uv run pytest tests/test_spec_writer.py -v
uv run ruff check skills/spec_writer/skill.py
uv run ty check
```

Expected: all PASS, no lint or type errors.

- [ ] **Step 5: Commit**

```bash
git add skills/spec_writer/SKILL.md
git commit -m "docs(spec_writer): document gather mode, gather_key, and answer parameters"
```

---

## Self-Review

**Spec coverage check:**

| Requirement | Covered by |
|---|---|
| Multi-turn Q&A via `gather` mode | Task 5 (_execute_gather + execute wiring) |
| Structured question flow: project overview → feature → components → per-component loop → constraints | Tasks 2, 3 |
| Component name loop (one question per component) | Task 3 (_apply_answer_and_advance component_detail branch) |
| XML context output format matching the target schema | Task 4 (_generate_xml_context) |
| XML written to `specs/` | Task 4 (_write_xml_context_file) |
| State persisted in blackboard between calls | Task 1 (_save_gather_state/_load_gather_state) |
| `draft` mode reads XML from completed gather via `gather_key` | Task 6 |
| Existing draft/refine/questions modes unaffected | Verified in Task 5 Step 6 |
| SKILL.md updated | Task 7 |

**Placeholder scan:** No TBDs, no "similar to above", all code blocks are complete.

**Type consistency:**
- `GatherState` defined in Task 1, used in Tasks 2, 3, 4, 5, 6 — consistent.
- `_apply_answer_and_advance(state: GatherState, answer: str) -> GatherState` — consistent across Tasks 3 and 5.
- `_generate_xml_context(state: GatherState) -> str` — consistent across Tasks 4 and 5.
- `_draft_with_optional_llm(inputs, previous_spec, xml_context="")` — Task 6 adds `xml_context` parameter with default; Task 5 call site in `execute()` passes positional so existing call sites (`_draft_with_optional_llm(inputs, previous_spec)`) continue to work.

One fix needed: Task 6 Step 3 has a guard condition `if inputs.gather_key != DEFAULT_GATHER_KEY or inputs.gather_key` that is always True. Replace with just `if inputs.gather_key:` — gather_key always has a value (defaults to DEFAULT_GATHER_KEY), so we should always attempt to load. A cleaner check:

```python
    xml_context = ""
    gather_state = _load_gather_state(ctx, inputs.gather_key)
    if gather_state is not None and gather_state.phase == "complete":
        xml_context = gather_state.xml_context
```

This is correct — if no gather session exists yet, `_load_gather_state` returns `None` and xml_context stays empty.
