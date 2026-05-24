from __future__ import annotations

import json
import logging
import shlex
import sqlite3
import threading
from typing import TYPE_CHECKING, Any

import yaml
from pydantic_ai.messages import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolReturnPart,
    UserPromptPart,
)

from harness_poc.console import print_error, print_markdown, print_skill_table, print_text
from harness_poc.core.events import (
    AgentInputAdded,
    AgentTurnRecorded,
    LLMActionEmitted,
    LLMTextEmitted,
)
from harness_poc.core.runtime import (
    AgentRunResult,
    GoalRunner,
    GoalRunResult,
    TokenAccounting,
    account_for_model_run,
    build_model,
    estimate_message_tokens,
    extract_observations_from_turn,
    prune_message_history,
    sanitize_new_messages,
    split_chat_turns,
)
from harness_poc.core.storage import StateSection, build_state_context

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from pathlib import Path

    from harness_poc.app_factory import AppState


MIN_WORKFLOW_PARTS = 2
WORKFLOW_OBJECTIVE_PARTS = 2
MIN_PIPELINE_PARTS = 2

# Tools whose results carry structural signal worth extracting as observations.
_SIGNAL_TOOLS: frozenset[str] = frozenset({
    "semble_search",
    "read_file",
    "search_files",
    "search_documents",
    "consolidate_state",
})


def _track_tokens(accounting: TokenAccounting, app_state: AppState) -> None:
    app_state.streaming.session_tokens += accounting.new_tokens


def run_repl(app_state: AppState) -> None:
    from harness_poc.app_factory import bootstrap_document_index  # noqa: PLC0415

    bootstrap_document_index(app_state.config, app_state.database)

    from harness_poc.tui import ChatApp  # noqa: PLC0415

    ChatApp(app_state).run()


def handle_repl_input(app_state: AppState, user_input: str) -> None:  # noqa: PLR0911
    if _is_repl_help_command(user_input):
        print_repl_help()
        return

    if _is_workflows_command(user_input):
        list_workflows(app_state)
        return

    if _is_workflow_command(user_input):
        handle_workflow_command(app_state, user_input)
        return

    if _is_pipelines_command(user_input):
        list_pipelines(app_state)
        return

    if _is_pipeline_command(user_input):
        handle_pipeline_command(app_state, user_input)
        return

    if _is_state_command(user_input):
        handle_state_command(app_state, user_input)
        return

    if _is_skill_command(user_input):
        handle_skill_command(app_state, user_input)
        return

    if _is_skills_command(user_input):
        list_skills(app_state)
        return

    if _is_copy_command(user_input):
        handle_copy_command(app_state)
        return

    if _is_goal_command(user_input):
        handle_goal_command(app_state, user_input)
        return

    if _handle_direct_resource_command(app_state, user_input):
        return

    handle_chat_input(app_state, user_input)


def _is_repl_help_command(user_input: str) -> bool:
    return user_input in {"/help", "help", "?"}


def _is_workflows_command(user_input: str) -> bool:
    return user_input in {"/workflows", "workflows"}


def _is_pipelines_command(user_input: str) -> bool:
    return user_input in {"/pipelines", "pipelines"}


def _is_skills_command(user_input: str) -> bool:
    return user_input in {"/skills", "skills"}


def _is_copy_command(user_input: str) -> bool:
    return user_input in {"/copy", "copy"}


def print_repl_help() -> None:
    print_text(
        """REPL commands:
  /goal <objective>
  /workflow <name> <objective>
  /workflows
  /pipeline <name> [key=value ...]
  /pipelines
  /state show [project|session|all]
  /state note <text>
  /state consolidate [preview|propose|approve]
  /skill list
  /skill show <name>
  /skills
  /copy
  /help
  /exit

Non-slash forms still work: goal, workflow, state, skill, exit, quit.""",
        markup=False,
    )


def run_workflow(app_state: AppState, workflow_name: str, objective: str) -> bool:
    if not workflow_name or not objective:
        print_text("Usage: workflow <name> <objective>")
        return False

    try:
        workflow_result = app_state.workflow_runner.run(
            workflow_name=workflow_name,
            inputs={"objective": objective},
            session_id=app_state.session_id,
        )
    except (
        OSError,
        KeyError,
        RuntimeError,
        TypeError,
        ValueError,
        yaml.YAMLError,
    ) as exc:
        print_error(f"Workflow failed: {exc}")
        return False

    summary = workflow_result.summary()
    print_text(summary)
    app_state.messages.append({"role": "assistant", "content": summary})
    return True


def handle_workflow_command(app_state: AppState, user_input: str) -> None:
    workflow_name, objective = _parse_workflow_command(user_input)
    run_workflow(app_state, workflow_name, objective)


def list_pipelines(app_state: AppState) -> None:
    names = app_state.pipeline_runner.list_pipelines()
    if not names:
        print_text("[dim]No pipelines found.[/dim]")
        return
    for name in names:
        print_text(f"  {name}")


def run_pipeline(app_state: AppState, pipeline_name: str, inputs: dict[str, str]) -> bool:
    if not pipeline_name:
        print_text("Usage: pipeline <name> [key=value ...]")
        return False
    try:
        result = app_state.pipeline_runner.run(pipeline_name, inputs, app_state)
    except FileNotFoundError as exc:
        print_error(str(exc))
        return False
    except (OSError, KeyError, RuntimeError, TypeError, ValueError, yaml.YAMLError) as exc:
        print_error(f"Pipeline failed: {exc}")
        return False

    status_color = "green" if result.status == "completed" else "red"
    print_text(
        f"\n[{status_color}]Pipeline '{pipeline_name}': {result.status}[/{status_color}]"
        f" ({result.duration_s:.1f}s)\n"
    )
    for node_id, node_result in result.node_results.items():
        node_color = {"completed": "green", "failed": "red", "skipped": "yellow"}.get(
            node_result.status, "white"
        )
        print_text(f"  [{node_color}]{node_id}: {node_result.status}[/{node_color}]")
        if node_result.output:
            print_markdown(node_result.output)

    summary = f"Pipeline '{pipeline_name}' {result.status}."
    app_state.messages.append({"role": "assistant", "content": summary})
    return result.status == "completed"


def handle_pipeline_command(app_state: AppState, user_input: str) -> None:
    pipeline_name, inputs = _parse_pipeline_command(user_input)
    run_pipeline(app_state, pipeline_name, inputs)


MAX_PYDANTIC_MESSAGES = 50


def _turn_has_signal_tools(messages: list[ModelMessage]) -> bool:
    """Return True if the turn contains any ToolReturnPart from a signal tool."""
    for msg in messages:
        if not isinstance(msg, ModelRequest):
            continue
        for part in msg.parts:
            if isinstance(part, ToolReturnPart) and part.tool_name in _SIGNAL_TOOLS:
                return True
    return False


def _build_turn_content(
    messages: list[ModelMessage],
    final_text: str,
) -> str:
    """Build a compact text representation of a turn for the classifier."""
    parts: list[str] = []
    for msg in messages:
        if not isinstance(msg, ModelRequest):
            continue
        for part in msg.parts:
            if isinstance(part, ToolReturnPart):
                tool_name = part.tool_name or "unknown_tool"
                content = str(part.content)[:4000]
                parts.append(f"[tool: {tool_name}]\n{content}")
            elif isinstance(part, TextPart):
                if part.content:
                    parts.append(f"[agent] {part.content[:2000]}")
    if final_text:
        parts.append(f"[agent final] {final_text[:2000]}")
    return "\n\n".join(parts) if parts else "(empty turn)"


def _fire_observations_async(app_state: AppState, response: object) -> None:
    """Fire observation extraction in a background thread.

    Captures the turn content and model config, then offloads the
    LLM call so the user isn't blocked.
    """
    if not isinstance(response, AgentRunResult):
        return

    turn_content = _build_turn_content(response.messages, response.content)
    if not turn_content or turn_content == "(empty turn)":
        return

    session_id = app_state.session_id
    skill_runner = app_state.skill_runner
    config = app_state.config

    def _run() -> None:
        model = build_model(config.llm)
        extract_observations_from_turn(
            turn_content,
            model=model,
            skill_runner=skill_runner,
            session_id=session_id,
        )

    thread = threading.Thread(target=_run, daemon=True, name="observe-extractor")
    thread.start()


def handle_chat_input(app_state: AppState, user_input: str) -> None:
    app_state.messages.append({"role": "user", "content": user_input})
    app_state.event_bus.publish(
        AgentInputAdded(session_id=app_state.session_id, user_content=user_input)
    )

    try:
        history = prune_message_history(
            app_state.pydantic_messages,
            max_tokens=app_state.config.runtime.chat_history_max_tokens,
            recent_turns=app_state.config.runtime.chat_history_recent_turns,
        )
        response = app_state.pydantic_runtime.stream_text(
            user_input,
            message_history=history,
            on_text=app_state.streaming.on_text,
            on_tool_event=app_state.streaming.on_tool_event,
        )
        if response.stop_reason == "tool_limit":
            logger.warning(
                "Chat turn hit tool limit",
                extra={"session_id": app_state.session_id},
            )
        fallback_messages = _pydantic_chat_exchange(user_input, response.content)
        accounting = account_for_model_run(
            response.usage,
            new_messages=response.messages,
            fallback_new_tokens=estimate_message_tokens(fallback_messages),
        )
        _track_tokens(accounting, app_state)
        _publish_llm_usage_event(app_state, accounting)
        new_messages = (
            sanitize_new_messages(
                response.messages,
                tool_result_max_chars=app_state.config.runtime.tool_result_max_chars,
            )
            if response.messages
            else fallback_messages
        )
        app_state.pydantic_messages.extend(new_messages)
        app_state.pydantic_messages = _bounded_pydantic_messages(app_state)
        blob = ModelMessagesTypeAdapter.dump_python(new_messages, mode="json")
        ordinal = app_state.database.append_session_messages(
            app_state.session_id,
            blob,
        )
        app_state.event_bus.publish(
            AgentTurnRecorded(
                session_id=app_state.session_id,
                messages_blob=blob,
                ordinal=ordinal,
            )
        )
        app_state.messages.append({"role": "assistant", "content": response.content})
        if response.content:
            app_state.event_bus.publish(
                LLMTextEmitted(
                    session_id=app_state.session_id,
                    content=response.content,
                )
            )
        app_state.streaming.on_finish(response.content)

        # --- Post-turn automatic observation extraction ---
        if response.messages and _turn_has_signal_tools(response.messages):
            _fire_observations_async(app_state, response)
    except sqlite3.OperationalError as exc:
        print_error(f"Database operation failed: {exc}")
    except (OSError, TypeError, ValueError, yaml.YAMLError) as exc:
        print_error(f"Tool execution failed: {exc}")


def _bounded_pydantic_messages(app_state: AppState) -> list[ModelMessage]:
    pruned = prune_message_history(
        app_state.pydantic_messages,
        max_tokens=app_state.config.runtime.chat_history_max_tokens,
        recent_turns=app_state.config.runtime.chat_history_recent_turns,
    )
    # Drop complete turns from the beginning if still over the message count
    # limit.  Raw slicing (pruned[excess:]) can break tool_call/tool_result
    # pairing, leaving orphaned tool-return messages that DeepSeek rejects
    # with: "Messages with role 'tool' must be a response to a preceding
    #        message with 'tool_calls'"
    while len(pruned) > MAX_PYDANTIC_MESSAGES:
        turns = split_chat_turns(pruned)
        if len(turns) <= 1:
            break
        pruned = [msg for turn in turns[1:] for msg in turn]
    return pruned


def _publish_llm_usage_event(app_state: AppState, accounting: TokenAccounting) -> None:
    model = app_state.config.llm.model
    app_state.event_bus.publish(
        LLMActionEmitted(
            session_id=app_state.session_id,
            model=model,
            tokens_used=accounting.new_tokens,
            input_tokens=accounting.input_tokens,
            output_tokens=accounting.output_tokens,
            billable_tokens=accounting.billable_tokens,
            new_tokens=accounting.new_tokens,
        )
    )


def _is_workflow_command(user_input: str) -> bool:
    return user_input.startswith(("workflow ", "/workflow "))


def _is_pipeline_command(user_input: str) -> bool:
    return user_input.startswith(("pipeline ", "/pipeline "))


def _parse_pipeline_command(user_input: str) -> tuple[str, dict[str, str]]:
    normalized = user_input.removeprefix("/").strip()
    parts = normalized.split(maxsplit=1)
    if len(parts) < MIN_PIPELINE_PARTS:
        return "", {}
    return _parse_pipeline_invocation(parts[1])


def _parse_pipeline_invocation(argument: str) -> tuple[str, dict[str, str]]:
    tokens = argument.split()
    if not tokens:
        return "", {}
    pipeline_name = tokens[0]
    inputs: dict[str, str] = {}
    current_key: str | None = None
    current_value_parts: list[str] = []
    for token in tokens[1:]:
        if "=" in token:
            if current_key is not None:
                inputs[current_key] = " ".join(current_value_parts)
            key, _, value = token.partition("=")
            current_key = key.strip()
            current_value_parts = [value] if value else []
        elif current_key is not None:
            current_value_parts.append(token)
    if current_key is not None:
        inputs[current_key] = " ".join(current_value_parts)
    return pipeline_name, inputs


def _parse_workflow_command(user_input: str) -> tuple[str, str]:
    normalized = user_input.removeprefix("/").strip()
    parts = normalized.split(maxsplit=WORKFLOW_OBJECTIVE_PARTS)
    if len(parts) < MIN_WORKFLOW_PARTS:
        return "", ""
    workflow_name = parts[1]
    objective = parts[2] if len(parts) > WORKFLOW_OBJECTIVE_PARTS else ""
    return workflow_name, objective


def list_workflows(app_state: AppState) -> None:
    workflow_files = sorted(app_state.config.paths.workflows.glob("*.yaml"))
    if not workflow_files:
        print_text("No workflows found.")
        return
    for workflow_file in workflow_files:
        print_text(f"- {workflow_file.stem}")


def _handle_direct_resource_command(app_state: AppState, user_input: str) -> bool:
    handled = False
    if user_input.startswith("/"):
        normalized = user_input.removeprefix("/").strip()
        if normalized:
            name, _, argument = normalized.partition(" ")
            matches = _direct_resource_matches(app_state, name)
            handled = bool(matches)
            if len(matches) > 1:
                print_error(
                    f"Ambiguous command '/{name}' matches: {', '.join(matches)}. "
                    "Use /skill, /workflow, or /pipeline to disambiguate."
                )
            elif matches == ["skill"]:
                execute_named_tool(app_state, name, argument)
            elif matches == ["workflow"]:
                run_workflow(app_state, name, argument)
            elif matches == ["pipeline"]:
                pipeline_name, inputs = _parse_pipeline_invocation(normalized)
                run_pipeline(app_state, pipeline_name, inputs)
    return handled


def _direct_resource_matches(app_state: AppState, name: str) -> list[str]:
    matches: list[str] = []
    if is_skill_name(app_state, name):
        matches.append("skill")
    if name in _workflow_names(app_state):
        matches.append("workflow")
    if name in app_state.pipeline_runner.list_pipelines():
        matches.append("pipeline")
    return matches


def _workflow_names(app_state: AppState) -> set[str]:
    workflows_dir = app_state.config.paths.workflows
    if not workflows_dir.exists():
        return set()
    return {path.stem for path in workflows_dir.glob("*.yaml")}


def _is_state_command(user_input: str) -> bool:
    return user_input == "state" or user_input.startswith(("state ", "/state "))


def handle_state_command(app_state: AppState, user_input: str) -> None:
    command, argument = _parse_state_command(user_input)

    try:
        handled = dispatch_state_command(app_state, command, argument)
    except (sqlite3.OperationalError, TypeError, ValueError) as exc:
        print_error(f"State command failed: {exc}")
        return

    if not handled:
        print_text(f"Unknown state command: {command}")
        print_state_help()


def dispatch_state_command(app_state: AppState, command: str, argument: str) -> bool:
    if command in {"", "help"}:
        print_state_help()
    elif command == "show":
        show_state(app_state, argument)
    elif command in {"note", "decision", "next", "question", "changelog"}:
        append_session_state(app_state, command, argument)
    elif command == "propose":
        propose_state(app_state)
    elif command == "approve":
        approve_state(app_state, argument)
    elif command == "reject":
        reject_state(app_state, argument)
    elif command == "consolidate":
        consolidate_state(app_state, argument)
    else:
        return False
    return True


def _parse_state_command(user_input: str) -> tuple[str, str]:
    normalized = user_input.removeprefix("/").strip()
    parts = normalized.split(maxsplit=WORKFLOW_OBJECTIVE_PARTS)
    if len(parts) == 1:
        return "help", ""
    command = parts[1]
    argument = parts[2] if len(parts) > WORKFLOW_OBJECTIVE_PARTS else ""
    return command, argument


def show_state(app_state: AppState, scope: str) -> None:
    project_state = app_state.database.ensure_project_state()
    session_state = app_state.database.ensure_session_state(app_state.session_id)
    normalized_scope = scope.strip() or "all"
    if normalized_scope == "project":
        print_markdown(project_state.to_markdown("Project State"))
        return
    if normalized_scope == "session":
        print_markdown(session_state.to_markdown("Current Session State"))
        return
    if normalized_scope != "all":
        msg = "state show accepts only project, session, all, or no scope"
        raise ValueError(msg)
    print_markdown(build_state_context(project_state, session_state))


def append_session_state(app_state: AppState, command: str, argument: str) -> None:
    if not argument:
        msg = f"state {command} requires text"
        raise ValueError(msg)
    section = _state_section_for_command(command)
    app_state.database.append_session_state(
        session_id=app_state.session_id,
        section=section,
        text=argument,
    )
    print_text(f"Added session state {section}: {argument}")


def propose_state(app_state: AppState) -> None:
    proposal = app_state.database.create_state_proposal(app_state.session_id)
    print_text(f"Created state proposal: [cyan]{proposal.proposal_id}[/cyan]")
    print_markdown(proposal.payload.to_markdown("Proposed Project State Additions"))


def approve_state(app_state: AppState, proposal_id: str) -> None:
    if not proposal_id:
        next_state = app_state.database.approve_latest_proposal()
        print_markdown(next_state.to_markdown("Updated Project State"))
        return
    app_state.database.approve_state_proposal(proposal_id)
    print_text(f"Approved state proposal: {proposal_id}")


def reject_state(app_state: AppState, proposal_id: str) -> None:
    if not proposal_id:
        msg = "state reject requires a proposal_id"
        raise ValueError(msg)
    app_state.database.reject_state_proposal(proposal_id)
    print_text(f"Rejected state proposal: {proposal_id}")


def consolidate_state(app_state: AppState, argument: str) -> None:
    mode = argument.strip() or "preview"
    result = app_state.skill_runner.execute_skill(
        tool_name="consolidate_state",
        arguments={"mode": mode},
        session_id=app_state.session_id,
    )
    if result.content.lstrip().startswith("##"):
        print_markdown(result.content)
        return
    print_text(result.content)


def _state_section_for_command(command: str) -> StateSection:
    if command == "note":
        return "notes"
    if command == "decision":
        return "decisions"
    if command == "next":
        return "next_actions"
    if command == "question":
        return "open_questions"
    if command == "changelog":
        return "changelog"
    msg = f"Unsupported state append command: {command}"
    raise ValueError(msg)


def print_state_help() -> None:
    print_text(
        """State commands:
  state show [project|session]
  state note <text>
  state decision <text>
  state next <text>
  state question <text>
  state changelog <entry>
  state propose
  state approve [proposal_id]
  state reject <proposal_id>
  state consolidate [preview|propose|approve]""",
        markup=False,
    )


def _is_skill_command(user_input: str) -> bool:
    return user_input == "skill" or user_input.startswith(("skill ", "/skill "))


def handle_skill_command(app_state: AppState, user_input: str) -> None:
    command, argument = _parse_skill_command(user_input)
    try:
        handled = dispatch_skill_command(app_state, command, argument)
    except (
        FileExistsError,
        OSError,
        TypeError,
        ValueError,
        yaml.YAMLError,
    ) as exc:
        print_error(f"Skill command failed: {exc}")
        return

    if not handled:
        print_text(f"Unknown skill command: {command}")
        print_skill_help()


def _parse_skill_command(user_input: str) -> tuple[str, str]:
    normalized = user_input.removeprefix("/").strip()
    parts = normalized.split(maxsplit=WORKFLOW_OBJECTIVE_PARTS)
    if len(parts) == 1:
        return "help", ""
    command = parts[1]
    argument = parts[2] if len(parts) > WORKFLOW_OBJECTIVE_PARTS else ""
    return command, argument


def dispatch_skill_command(app_state: AppState, command: str, argument: str) -> bool:
    if command in {"", "help"}:
        print_skill_help()
    elif command == "list":
        list_skills(app_state)
    elif command == "show":
        show_skill(app_state, argument)
    elif command == "create":
        create_skill(app_state, argument)
    elif is_skill_name(app_state, command):
        execute_named_tool(app_state, command, argument)
    else:
        return False
    return True


def find_skill_files(app_state: AppState) -> list[Path]:
    skill_files: list[Path] = []
    for skills_dir in (
        app_state.config.paths.system_skills,
        app_state.config.paths.project_skills,
    ):
        if skills_dir.exists():
            skill_files.extend(sorted(skills_dir.glob("*/SKILL.md")))
    return skill_files


def list_skills(app_state: AppState) -> None:
    print_skill_table(find_skill_files(app_state), app_state.skill_runner)


def handle_copy_command(app_state: AppState) -> None:
    for msg in reversed(app_state.messages):
        if msg.get("role") == "assistant" and msg.get("content"):
            import subprocess  # noqa: PLC0415

            content = msg["content"]
            try:
                subprocess.run(["pbcopy"], input=content.encode(), check=True)  # noqa: S607
                print_text("Last response copied to clipboard.")
            except (FileNotFoundError, subprocess.CalledProcessError):
                print_text(content)
            return
    print_text("No response to copy.")


def is_skill_name(app_state: AppState, skill_name: str) -> bool:
    return skill_name in {
        tool["function"]["name"]
        for tool in app_state.skill_runner.discover_skills()
        if isinstance(tool.get("function"), dict) and isinstance(tool["function"].get("name"), str)
    }


def execute_named_tool(app_state: AppState, skill_name: str, argument: str) -> None:
    result = app_state.skill_runner.execute_skill(
        tool_name=skill_name,
        arguments=_parse_skill_arguments(app_state, skill_name, argument),
        session_id=app_state.session_id,
    )
    if result.content.lstrip().startswith("##"):
        print_markdown(result.content)
        return
    print_text(result.content)


def show_skill(app_state: AppState, skill_name: str) -> None:
    normalized_name = skill_name.strip()
    if not normalized_name:
        msg = "skill show requires a skill name"
        raise ValueError(msg)
    for skills_dir in (
        app_state.config.paths.system_skills,
        app_state.config.paths.project_skills,
    ):
        skill_file = skills_dir / normalized_name / "SKILL.md"
        if skill_file.exists():
            print_markdown(skill_file.read_text(encoding="utf-8").strip())
            return
    msg = f"Skill not found: {normalized_name}"
    raise ValueError(msg)


def create_skill(app_state: AppState, argument: str) -> None:
    skill_name, description = _parse_create_skill_args(argument)
    scaffolded = app_state.skill_scaffolder.create_skill(skill_name, description)
    app_state.tools = app_state.skill_runner.discover_skills()
    print_text(f"Created skill: [cyan]{scaffolded.skill_name}[/cyan]")
    for path in scaffolded.created_files:
        print_text(f"- {path.relative_to(app_state.config.project_root)}")


def _parse_create_skill_args(argument: str) -> tuple[str, str]:
    parts = argument.strip().split(maxsplit=1)
    if len(parts) < MIN_WORKFLOW_PARTS:
        msg = "Usage: skill create <name> <description>"
        raise ValueError(msg)
    return parts[0], parts[1]


def _parse_skill_arguments(app_state: AppState, skill_name: str, argument: str) -> dict[str, Any]:
    normalized = argument.strip()
    if not normalized:
        return {}
    if normalized.startswith("{"):
        decoded = json.loads(normalized)
        if not isinstance(decoded, dict):
            msg = "Skill JSON arguments must be an object"
            raise TypeError(msg)
        return decoded

    values = shlex.split(normalized)
    key_value_args = _parse_key_value_args(values)
    if key_value_args:
        return key_value_args
    if len(values) == 1:
        return {_primary_skill_argument(app_state, skill_name): values[0]}
    return {"args": values}


def _parse_key_value_args(values: list[str]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            return {}
        key, raw_value = value.split("=", maxsplit=1)
        if not key:
            return {}
        parsed[key] = raw_value
    return parsed


def _primary_skill_argument(app_state: AppState, skill_name: str) -> str:
    skill_file = _find_skill_file(app_state, skill_name)
    if skill_file is None:
        return "memory_key"
    skill = app_state.skill_runner.parse_skill_document(skill_file)
    parameters = skill["metadata"]["parameters"]
    required = parameters.get("required")
    if isinstance(required, list):
        for item in required:
            if isinstance(item, str):
                return item
    properties = parameters.get("properties")
    if isinstance(properties, dict):
        for key in properties:
            return str(key)
    return "memory_key"


def _find_skill_file(app_state: AppState, skill_name: str) -> Path | None:
    for skill_file in find_skill_files(app_state):
        skill = app_state.skill_runner.parse_skill_document(skill_file)
        if skill["metadata"]["name"] == skill_name:
            return skill_file
    return None


def print_skill_help() -> None:
    print_text(
        """Skill commands:
  skill list
  skill show <name>
  skill create <name> <description>
  skill <name> [args|key=value|json-object]""",
        markup=False,
    )


# ------------------------------------------------------------------
# /goal command
# ------------------------------------------------------------------


def _is_goal_command(user_input: str) -> bool:
    return user_input.startswith(("/goal ", "goal "))


def handle_goal_command(app_state: AppState, user_input: str) -> None:
    objective = user_input.removeprefix("/").removeprefix("goal").strip()
    if not objective:
        print_text("Usage: /goal <objective>")
        return

    print_text("[cyan]Starting autonomous goal loop...[/cyan]")
    print_text(f"Goal: [bold]{objective}[/bold]")
    print_text("")

    runner = GoalRunner()
    try:
        result = runner.run(
            goal=objective,
            app_state=app_state,
            on_text=app_state.streaming.on_text,
            on_tool_event=app_state.streaming.on_tool_event,
        )
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        logger.exception(
            "REPL goal command failed",
            extra={"session_id": app_state.session_id, "objective": objective},
        )
        print_error(f"Goal loop failed: {exc}")
        return

    _print_goal_result(result)
    _append_goal_result_to_chat_history(app_state, user_input, result)


def _print_goal_result(result: object) -> None:
    if not isinstance(result, GoalRunResult):
        return

    status_style = {
        "completed": "green",
        "budget_exhausted": "yellow",
        "error": "red",
    }
    color = status_style.get(result.status, "white")

    print_text("")
    print_text(f"[{color}]Status: {result.status}[/{color}]")
    print_text(f"Iterations: {result.iterations}")
    print_text(f"Total tokens: {result.total_tokens}")
    print_text("")
    print_markdown(result.content)

    if result.events:
        print_text("")
        print_text("[dim]--- Event Log ---[/dim]")
        for i, event in enumerate(result.events, 1):
            event_type = event.get("type", "?")
            tool = event.get("tool", "?")
            status = event.get("status", "")
            extra = f" ({status})" if status else ""
            print_text(f"[dim]{i}. [{event_type}] {tool}{extra}[/dim]")


def _append_goal_result_to_chat_history(
    app_state: AppState,
    user_input: str,
    result: GoalRunResult,
) -> None:
    assistant_content = (
        f"Goal status: {result.status}\n"
        f"Iterations: {result.iterations}\n"
        f"Total tokens: {result.total_tokens}\n\n"
        f"{result.content}"
    )
    app_state.messages.append({"role": "user", "content": user_input})
    app_state.messages.append({"role": "assistant", "content": assistant_content})
    _append_pydantic_chat_exchange(app_state, user_input, assistant_content)


def _append_pydantic_chat_exchange(
    app_state: AppState,
    user_content: str,
    assistant_content: str,
) -> None:
    app_state.pydantic_messages.extend(_pydantic_chat_exchange(user_content, assistant_content))


def _pydantic_chat_exchange(user_content: str, assistant_content: str) -> list[ModelMessage]:
    return [
        ModelRequest(parts=[UserPromptPart(content=user_content)]),
        ModelResponse(parts=[TextPart(content=assistant_content)]),
    ]
