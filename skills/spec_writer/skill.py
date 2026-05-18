import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from harness_poc.core.llm_client import LLMClient, Message
from harness_poc.core.skill_context import SkillContext, SkillResult

DEFAULT_OUTPUT_KEY = "spec_writer_result"
DEFAULT_GATHER_KEY = "spec_gather_state"
MAX_QUESTIONS = 3
VALID_MODES = {"draft", "refine", "questions", "gather"}
SPEC_HEADINGS = (
    "## Objective",
    "## Background",
    "## Requirements",
    "## Non-Goals",
    "## Proposed Behavior",
    "## Acceptance Criteria",
    "## Test Plan",
    "## Open Questions",
)


GatherPhase = Literal[
    "awaiting_project_overview",
    "awaiting_feature_request",
    "awaiting_components_list",
    "awaiting_component_detail",
    "awaiting_constraints",
    "complete",
]


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


def _parse_component_names(answer: str) -> list[str]:
    names: list[str] = []
    for line in answer.splitlines():
        stripped_line = line.strip(" \t-•*")
        if not stripped_line:
            continue
        for part in stripped_line.split(","):
            stripped_part = part.strip()
            if stripped_part:
                names.append(stripped_part)
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


def execute(ctx: SkillContext, arguments: dict[str, Any]) -> SkillResult:
    inputs = _parse_inputs(arguments)

    if inputs.mode == "gather":
        return _execute_gather(ctx, inputs)

    questions = _clarifying_questions(inputs)

    if inputs.mode == "questions":
        return _questions_result(questions)

    if questions:
        return SkillResult(
            status="needs_orchestrator_action",
            content=_format_questions(questions),
            artifacts={"questions": questions, "mode": inputs.mode},
        )

    previous_spec = _previous_spec(ctx, inputs) if inputs.mode == "refine" else ""
    if inputs.mode == "refine" and not previous_spec:
        return SkillResult(
            status="blocked",
            content=(
                "No previous spec draft was found. Run spec_writer in draft mode "
                "first, or provide an output_key with an existing draft."
            ),
            artifacts={"output_key": inputs.output_key},
        )

    xml_context = ""
    gather_state = _load_gather_state(ctx, inputs.gather_key)
    if gather_state is not None and gather_state.phase == "complete":
        xml_context = gather_state.xml_context

    spec, used_llm = _draft_with_optional_llm(inputs, previous_spec, xml_context)
    spec_path = _write_spec_file(ctx.project_root, spec, inputs)
    ctx.database.write_memory(
        ctx.session_id,
        inputs.output_key,
        {
            "spec": spec,
            "spec_path": str(spec_path.relative_to(ctx.project_root)),
            "mode": inputs.mode,
            "updated_at": datetime.now(UTC).isoformat(),
        },
    )

    return SkillResult(
        status="success",
        content=spec,
        artifacts={
            "mode": inputs.mode,
            "output_key": inputs.output_key,
            "spec_path": str(spec_path.relative_to(ctx.project_root)),
            "used_llm": used_llm,
        },
    )


def _parse_inputs(arguments: dict[str, Any]) -> SpecInputs:
    mode = str(arguments.get("mode") or "draft").strip().lower()
    if mode not in VALID_MODES:
        msg = f"spec_writer mode must be one of {sorted(VALID_MODES)}"
        raise ValueError(msg)

    goal = _string_value(arguments, "goal")
    args = arguments.get("args")
    if not goal and isinstance(args, list) and args:
        goal = " ".join(str(value) for value in args).strip()

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


def _string_value(arguments: dict[str, Any], key: str) -> str:
    value = arguments.get(key)
    return "" if value is None else str(value).strip()


def _bool_value(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _clarifying_questions(inputs: SpecInputs) -> list[str]:
    questions: list[str] = []
    if not inputs.goal:
        questions.append("What feature, change, or behavior should this spec cover?")
    if not inputs.context:
        questions.append(
            "What existing behavior, code area, or user workflow should the spec account for?"
        )
    if not inputs.requirements:
        questions.append(
            "What must be true for the implementation to be accepted?"
        )
    return questions[:MAX_QUESTIONS]


def _questions_result(questions: list[str]) -> SkillResult:
    fallback_questions = questions or [
        "Are there any constraints, non-goals, or acceptance criteria missing?"
    ]
    return SkillResult(
        status="needs_orchestrator_action",
        content=_format_questions(fallback_questions),
        artifacts={"questions": fallback_questions, "mode": "questions"},
    )


def _format_questions(questions: list[str]) -> str:
    lines = ["## Clarifying Questions", ""]
    lines.extend(f"{index}. {question}" for index, question in enumerate(questions, 1))
    return "\n".join(lines)


def _previous_spec(ctx: SkillContext, inputs: SpecInputs) -> str:
    payload = ctx.database.read_memory(ctx.session_id, inputs.output_key)
    if isinstance(payload, dict):
        spec = payload.get("spec")
        return spec if isinstance(spec, str) else ""
    return payload if isinstance(payload, str) else ""


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


def _should_try_llm() -> bool:
    return not LLMClient().use_mock


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


def _llm_messages(inputs: SpecInputs, previous_spec: str) -> list[Message]:
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
                f"Mode: {inputs.mode}\n"
                f"Title: {_spec_title(inputs)}\n"
                f"Goal: {inputs.goal}\n"
                f"Context: {inputs.context}\n"
                f"Requirements: {inputs.requirements}\n"
                f"Constraints: {inputs.constraints}\n"
                f"Non-goals: {inputs.non_goals}\n"
                f"Open questions: {inputs.open_questions}\n\n"
                f"Previous spec:\n{previous_spec}"
            ),
        },
    ]


def _is_valid_spec(spec: str) -> bool:
    return bool(spec.startswith("# ")) and all(
        heading in spec for heading in SPEC_HEADINGS
    )


def _deterministic_spec(inputs: SpecInputs, previous_spec: str) -> str:
    title = _spec_title(inputs)
    requirements = _lines_or_default(
        inputs.requirements,
        "Implement the requested behavior without regressing existing workflows.",
    )
    constraints = _lines_or_default(
        inputs.constraints,
        "Follow existing project patterns and keep the change narrowly scoped.",
    )
    non_goals = _lines_or_default(inputs.non_goals, "No explicit non-goals provided.")
    open_questions = _lines_or_default(
        inputs.open_questions,
        "No open questions recorded.",
    )
    refinement_note = (
        f"\n\nPrevious draft considered:\n\n{previous_spec.strip()}"
        if previous_spec
        else ""
    )

    return "\n".join(
        [
            f"# {title}",
            "",
            "## Objective",
            inputs.goal,
            "",
            "## Background",
            inputs.context,
            refinement_note,
            "",
            "## Requirements",
            requirements,
            "",
            "## Non-Goals",
            non_goals,
            "",
            "## Proposed Behavior",
            "\n".join(
                [
                    "- Add or change the smallest coherent surface that satisfies the objective.",
                    f"- Respect these constraints: {constraints}",
                    "- Preserve discoverability, testability, and existing command behavior.",
                ],
            ),
            "",
            "## Acceptance Criteria",
            (
                "- The requested behavior is available through the expected user path.\n"
                "- Errors and unclear input produce actionable feedback.\n"
                "- Existing related tests continue to pass."
            ),
            "",
            "## Test Plan",
            (
                "- Add focused unit tests for success and unclear-input paths.\n"
                "- Run the targeted pytest file for the changed behavior.\n"
                "- Run lint/type checks if shared interfaces changed."
            ),
            "",
            "## Open Questions",
            open_questions,
        ],
    )


def _lines_or_default(value: str, default: str) -> str:
    if not value:
        return f"- {default}"
    lines = [line.strip(" -") for line in value.splitlines() if line.strip()]
    return "\n".join(f"- {line}" for line in lines)


def _spec_title(inputs: SpecInputs) -> str:
    if inputs.title:
        return inputs.title
    words = re.findall(r"[A-Za-z0-9]+", inputs.goal)[:8]
    return " ".join(words).title() if words else "Implementation Spec"


def _write_spec_file(project_root: Path, spec: str, inputs: SpecInputs) -> Path:
    specs_dir = project_root / "specs"
    specs_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    path = specs_dir / f"{timestamp}-{_slugify(_spec_title(inputs))}.md"
    path.write_text(spec.rstrip() + "\n", encoding="utf-8")
    return path


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "implementation-spec"
