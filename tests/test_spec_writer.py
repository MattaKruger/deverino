# ruff: noqa: PLC0415, TC001

from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine

from harness_poc.core.config import (
    HarnessConfig,
    HarnessPaths,
    LLMConfig,
    ObservabilityConfig,
    RuntimeConfig,
)
from harness_poc.core.database import BlackboardDatabase
from harness_poc.core.skill_context import SkillResult
from harness_poc.core.skill_runner import SkillRunner

MAX_QUESTIONS = 3


def test_spec_writer_questions_mode_returns_focused_questions(
    tmp_path: Path,
    db_engine: Engine,
) -> None:
    runner, session_id, _database = _runner(tmp_path, db_engine)

    result = runner.execute_skill(
        tool_name="spec_writer",
        arguments={"mode": "questions"},
        session_id=session_id,
    )

    assert result.status == "needs_orchestrator_action"
    assert len(result.artifacts["questions"]) <= MAX_QUESTIONS
    assert "Clarifying Questions" in result.content


def test_spec_writer_draft_requires_enough_intent(tmp_path: Path, db_engine: Engine) -> None:
    runner, session_id, _database = _runner(tmp_path, db_engine)

    result = runner.execute_skill(
        tool_name="spec_writer",
        arguments={"goal": "Add export support"},
        session_id=session_id,
    )

    assert result.status == "needs_orchestrator_action"
    assert "existing behavior" in result.content


def test_spec_writer_draft_writes_spec_file_and_memory(tmp_path: Path, db_engine: Engine) -> None:
    runner, session_id, database = _runner(tmp_path, db_engine)

    result = runner.execute_skill(
        tool_name="spec_writer",
        arguments={
            "goal": "Add a spec writer skill",
            "context": "The harness executes project-local skills from the REPL.",
            "requirements": "Write markdown specs to disk",
            "open_questions": "Should this become a workflow later?",
        },
        session_id=session_id,
    )

    assert result.status == "success"
    assert "# Add A Spec Writer Skill" in result.content
    for heading in (
        "## Objective",
        "## Background",
        "## Requirements",
        "## Open Questions",
    ):
        assert heading in result.content
    assert "Should this become a workflow later?" in result.content

    spec_path = Path(result.artifacts["spec_path"])
    assert spec_path.parts[0] == "specs"
    assert (tmp_path / spec_path).exists()

    memory = database.read_memory(session_id, "spec_writer_result")
    assert isinstance(memory, dict)
    assert memory["spec"] == result.content
    assert memory["spec_path"] == str(spec_path)


def test_spec_writer_refine_uses_previous_draft(tmp_path: Path, db_engine: Engine) -> None:
    runner, session_id, database = _runner(tmp_path, db_engine)
    database.write_memory(
        session_id,
        "existing_spec",
        {"spec": "# Existing Spec\n\n## Objective\nOld objective"},
    )

    result = runner.execute_skill(
        tool_name="spec_writer",
        arguments={
            "mode": "refine",
            "output_key": "existing_spec",
            "goal": "Refine the existing spec",
            "context": "A previous draft exists in memory.",
            "requirements": "Preserve useful previous context",
        },
        session_id=session_id,
    )

    assert result.status == "success"
    assert "Previous draft considered" in result.content
    assert "Old objective" in result.content


def _runner(tmp_path: Path, db_engine: Engine) -> tuple[SkillRunner, str, BlackboardDatabase]:
    config = _test_config(tmp_path, db_engine)
    database = BlackboardDatabase(db_engine)
    session_id = database.start_session("test")
    return SkillRunner(database=database, config=config), session_id, database


def _test_config(tmp_path: Path, engine: Engine) -> HarnessConfig:
    repo_root = Path.cwd()
    return HarnessConfig(
        project_root=tmp_path,
        config_path=repo_root / "harness.yaml",
        paths=HarnessPaths(
            soul=repo_root / "harness_poc/system_prompts/SOUL.md",
            system_tools=repo_root / "harness_poc/system_tools",
            system_skills=repo_root / "harness_poc/system_skills",
            project_skills=repo_root / "skills",
            workflows=repo_root / "workflows",
            pipelines=repo_root / "pipelines",
            personas=repo_root / "personas",
        ),
        runtime=RuntimeConfig(
            database_url=engine.url.render_as_string(hide_password=False),
            default_container_image="python:3.14-slim",
        ),
        observability=ObservabilityConfig(logfire_enabled=False),
        llm=LLMConfig(provider="deepseek", model="deepseek-v4-flash", base_url=None),
    )


def test_gather_state_round_trips_through_blackboard(tmp_path: Path, db_engine: Engine) -> None:
    _runner_obj, session_id, database = _runner(tmp_path, db_engine)
    config = _test_config(tmp_path, db_engine)
    from harness_poc.core.skill_context import SkillContext
    from skills.spec_writer.skill import (
        GatherState,
        _load_gather_state,
        _save_gather_state,
    )

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


def test_load_gather_state_returns_none_when_missing(tmp_path: Path, db_engine: Engine) -> None:
    _runner_obj, session_id, database = _runner(tmp_path, db_engine)
    config = _test_config(tmp_path, db_engine)
    from harness_poc.core.skill_context import SkillContext
    from skills.spec_writer.skill import _load_gather_state

    ctx = SkillContext(
        session_id=session_id,
        skill_name="spec_writer",
        database=database,
        config=config,
    )
    assert _load_gather_state(ctx, "nonexistent_key") is None


def test_parse_component_names_handles_comma_separated() -> None:
    from skills.spec_writer.skill import _parse_component_names

    result = _parse_component_names("GoalRunner, EvalSkill, LoopGuard")
    assert result == ["GoalRunner", "EvalSkill", "LoopGuard"]


def test_parse_component_names_handles_bullet_list() -> None:
    from skills.spec_writer.skill import _parse_component_names

    result = _parse_component_names("- GoalRunner\n- EvalSkill\n- LoopGuard")
    assert result == ["GoalRunner", "EvalSkill", "LoopGuard"]


def test_parse_component_names_handles_mixed_format() -> None:
    from skills.spec_writer.skill import _parse_component_names

    result = _parse_component_names("GoalRunner\nEvalSkill, LoopGuard")
    assert result == ["GoalRunner", "EvalSkill", "LoopGuard"]


def test_parse_component_names_strips_empty_lines() -> None:
    from skills.spec_writer.skill import _parse_component_names

    result = _parse_component_names("\n- Alpha\n\n- Beta\n")
    assert result == ["Alpha", "Beta"]


def test_question_for_phase_project_overview() -> None:
    from skills.spec_writer.skill import GatherState, _question_for_phase

    state = GatherState(phase="awaiting_project_overview")
    q = _question_for_phase(state)
    assert "project" in q.lower()
    assert "1/4" in q


def test_question_for_phase_components_list() -> None:
    from skills.spec_writer.skill import GatherState, _question_for_phase

    state = GatherState(phase="awaiting_components_list")
    q = _question_for_phase(state)
    assert "component" in q.lower()


def test_question_for_phase_component_detail_names_component() -> None:
    from skills.spec_writer.skill import GatherState, _question_for_phase

    state = GatherState(
        phase="awaiting_component_detail",
        component_names=["GoalRunner", "EvalSkill"],
        current_component_index=0,
    )
    q = _question_for_phase(state)
    assert "GoalRunner" in q
    assert "1/2" in q


def test_question_for_phase_component_detail_second_component() -> None:
    from skills.spec_writer.skill import GatherState, _question_for_phase

    state = GatherState(
        phase="awaiting_component_detail",
        component_names=["GoalRunner", "EvalSkill"],
        current_component_index=1,
    )
    q = _question_for_phase(state)
    assert "EvalSkill" in q
    assert "2/2" in q


def test_apply_answer_project_overview_advances_to_feature_request() -> None:
    from skills.spec_writer.skill import GatherState, _apply_answer_and_advance

    state = GatherState(phase="awaiting_project_overview")
    result = _apply_answer_and_advance(state, "A Python harness for LLM agents.")
    assert result.phase == "awaiting_feature_request"
    assert result.project_overview == "A Python harness for LLM agents."


def test_apply_answer_feature_request_advances_to_components_list() -> None:
    from skills.spec_writer.skill import GatherState, _apply_answer_and_advance

    state = GatherState(phase="awaiting_feature_request", project_overview="...")
    result = _apply_answer_and_advance(state, "Add an autonomous goal loop.")
    assert result.phase == "awaiting_components_list"
    assert result.feature_request == "Add an autonomous goal loop."


def test_apply_answer_components_list_advances_to_component_detail() -> None:
    from skills.spec_writer.skill import GatherState, _apply_answer_and_advance

    state = GatherState(phase="awaiting_components_list")
    result = _apply_answer_and_advance(state, "GoalRunner, EvalSkill")
    assert result.phase == "awaiting_component_detail"
    assert result.component_names == ["GoalRunner", "EvalSkill"]
    assert result.current_component_index == 0


def test_apply_answer_component_detail_loops_to_next_component() -> None:
    from skills.spec_writer.skill import GatherState, _apply_answer_and_advance

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
    from skills.spec_writer.skill import GatherState, _apply_answer_and_advance

    state = GatherState(
        phase="awaiting_component_detail",
        component_names=["GoalRunner", "EvalSkill"],
        current_component_index=1,
    )
    result = _apply_answer_and_advance(state, "Acts as the exit mechanism.")
    assert result.phase == "awaiting_constraints"
    assert result.component_details["EvalSkill"] == "Acts as the exit mechanism."


def test_apply_answer_constraints_advances_to_complete() -> None:
    from skills.spec_writer.skill import GatherState, _apply_answer_and_advance

    state = GatherState(phase="awaiting_constraints")
    result = _apply_answer_and_advance(state, "No external frameworks.")
    assert result.phase == "complete"
    assert result.constraints == "No external frameworks."


def test_apply_answer_empty_answer_does_not_advance() -> None:
    from skills.spec_writer.skill import GatherState, _apply_answer_and_advance

    state = GatherState(phase="awaiting_project_overview")
    result = _apply_answer_and_advance(state, "")
    assert result.phase == "awaiting_project_overview"
    assert result.project_overview == ""


def test_generate_xml_context_includes_all_sections() -> None:
    from skills.spec_writer.skill import GatherState, _generate_xml_context

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
    from skills.spec_writer.skill import _write_xml_context_file

    xml = "<context><project_overview>Test</project_overview></context>"
    path = _write_xml_context_file(tmp_path, xml)
    assert path.exists()
    assert path.suffix == ".xml"
    assert path.read_text() == xml + "\n"


def test_gather_first_call_asks_project_overview(tmp_path: Path, db_engine: Engine) -> None:
    runner, session_id, _ = _runner(tmp_path, db_engine)
    result = runner.execute_skill(
        tool_name="spec_writer",
        arguments={"mode": "gather", "gather_key": "test_gather"},
        session_id=session_id,
    )
    assert result.status == "needs_orchestrator_action"
    assert "project" in result.content.lower()
    assert result.artifacts["phase"] == "awaiting_project_overview"
    assert result.artifacts["gather_key"] == "test_gather"


def test_gather_answer_advances_to_next_phase(tmp_path: Path, db_engine: Engine) -> None:
    runner, session_id, _ = _runner(tmp_path, db_engine)
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


def test_gather_full_flow_produces_xml(tmp_path: Path, db_engine: Engine) -> None:
    runner, session_id, _ = _runner(tmp_path, db_engine)
    key = "full_gather_test"

    def call(answer: str = "") -> SkillResult:
        return runner.execute_skill(
            tool_name="spec_writer",
            arguments={"mode": "gather", "gather_key": key, "answer": answer},
            session_id=session_id,
        )

    call()  # ask project overview
    call("A Python LLM harness.")  # answer project overview → feature_request
    call("Add an autonomous goal loop.")  # answer feature request → components_list
    call("GoalRunner, EvalSkill")  # answer components list → component_detail[0]
    call("Manages the while loop.")  # answer GoalRunner → component_detail[1]
    result = call("Acts as exit mechanism.")  # answer EvalSkill → constraints
    assert result.artifacts["phase"] == "awaiting_constraints"

    result = call("No external frameworks.")  # answer constraints → complete
    assert result.status == "success"
    assert "<context>" in result.content
    assert "A Python LLM harness." in result.content
    assert "GoalRunner" in result.content
    assert "No external frameworks." in result.content
    assert result.artifacts["phase"] == "complete"

    xml_path = Path(result.artifacts["xml_path"])
    assert xml_path.parts[0] == "specs"
    assert (tmp_path / xml_path).exists()


def test_gather_uses_default_gather_key_when_not_provided(
    tmp_path: Path,
    db_engine: Engine,
) -> None:
    runner, session_id, _ = _runner(tmp_path, db_engine)
    result = runner.execute_skill(
        tool_name="spec_writer",
        arguments={"mode": "gather"},
        session_id=session_id,
    )
    assert result.artifacts["gather_key"] == "spec_gather_state"


def test_draft_with_gather_key_reads_completed_xml_from_blackboard(
    tmp_path: Path,
    db_engine: Engine,
) -> None:
    runner, session_id, database = _runner(tmp_path, db_engine)
    config = _test_config(tmp_path, db_engine)
    from harness_poc.core.skill_context import SkillContext
    from skills.spec_writer.skill import GatherState, _save_gather_state

    ctx = SkillContext(
        session_id=session_id,
        skill_name="spec_writer",
        database=database,
        config=config,
    )
    completed_state = GatherState(
        phase="complete",
        project_overview="A Python harness.",
        feature_request="Add goal loop.",
        component_names=["GoalRunner"],
        component_details={"GoalRunner": "Manages the loop."},
        constraints="No external frameworks.",
        xml_context="<context>prefilled xml</context>",
    )
    _save_gather_state(ctx, "prefilled_gather", completed_state)

    result = runner.execute_skill(
        tool_name="spec_writer",
        arguments={
            "mode": "draft",
            "goal": "Add goal loop",
            "context": "A Python harness.",
            "requirements": "Implement a while loop",
            "gather_key": "prefilled_gather",
            "use_llm": False,
        },
        session_id=session_id,
    )
    assert result.status == "success"
    assert "## Objective" in result.content


def test_draft_without_gather_key_works_as_before(tmp_path: Path, db_engine: Engine) -> None:
    runner, session_id, _ = _runner(tmp_path, db_engine)
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
