from __future__ import annotations

import json
import logging
import shlex
import sqlite3
from typing import TYPE_CHECKING, Any

import yaml
from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.history import FileHistory
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart

from harness_poc.console import console, print_error, print_markdown, print_skill_table
from harness_poc.core.goal_runner import GoalRunner, GoalRunResult
from harness_poc.core.state import StateSection, build_state_context
from harness_poc.repl_completion import HarnessCompleter

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from pathlib import Path

    from harness_poc.app_factory import AppState
    from harness_poc.core.llm_client import Usage


MIN_WORKFLOW_PARTS = 2
WORKFLOW_OBJECTIVE_PARTS = 2
MIN_PIPELINE_PARTS = 2
TOKEN_MILLION = 1_000_000
TOKEN_THOUSAND = 1_000

_session_token_count: int = 0
_session_cache_hit_tokens: int = 0


def _track_tokens(usage: Usage | None) -> None:
    """Accumulate API-reported token usage into the session counter.

    Falls back to 0 when usage is unavailable (mock mode).
    Uses total_tokens from the API, which already accounts for cache discounts.
    """
    global _session_token_count, _session_cache_hit_tokens  # noqa: PLW0603
    if usage is not None:
        _session_token_count += usage.get("total_tokens", 0)
        _session_cache_hit_tokens += usage.get("cache_hit_tokens", 0)


def run_repl(app_state: AppState) -> None:
    console.print(f"Started session: [cyan]{app_state.session_id}[/cyan]")
    console.print("Type 'exit' or 'quit' to stop.")
    console.print("Run an explicit workflow with: workflow research_task <objective>")
    console.print("Run a pipeline with: pipeline <name> [key=value ...]")
    console.print("Run an autonomous goal loop with: /goal <objective>")
    console.print("Manage STATE with: state show | state note <text> | state propose")
    console.print("Manage skills with: skill list | skill create <name> <description>")
    console.print("Type '/' and press Tab to discover slash commands.")
    session: PromptSession[str] = PromptSession(
        completer=HarnessCompleter(app_state),
        complete_while_typing=True,
        history=FileHistory(str(app_state.config.project_root / ".harness_repl_history")),
    )

    while True:
        try:
            user_input = session.prompt(_build_prompt_bar(app_state)).strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\nExiting.")
            break

        if user_input.lower() in {"exit", "quit", "/exit", "/quit"}:
            break
        if not user_input:
            continue

        handle_repl_input(app_state, user_input)


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

    if _is_goal_command(user_input):
        handle_goal_command(app_state, user_input)
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


def print_repl_help() -> None:
    console.print(
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
  /help
  /exit

Non-slash forms still work: goal, workflow, state, skill, exit, quit.""",
        markup=False,
    )


def run_workflow(app_state: AppState, workflow_name: str, objective: str) -> bool:
    if not workflow_name or not objective:
        console.print("Usage: workflow <name> <objective>")
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
    console.print(summary)
    app_state.messages.append({"role": "assistant", "content": summary})
    return True


def handle_workflow_command(app_state: AppState, user_input: str) -> None:
    workflow_name, objective = _parse_workflow_command(user_input)
    run_workflow(app_state, workflow_name, objective)


def list_pipelines(app_state: AppState) -> None:
    names = app_state.pipeline_runner.list_pipelines()
    if not names:
        console.print("[dim]No pipelines found.[/dim]")
        return
    for name in names:
        console.print(f"  {name}")


def run_pipeline(app_state: AppState, pipeline_name: str, inputs: dict[str, str]) -> bool:
    if not pipeline_name:
        console.print("Usage: pipeline <name> [key=value ...]")
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
    console.print(
        f"\n[{status_color}]Pipeline '{pipeline_name}': {result.status}[/{status_color}]"
        f" ({result.duration_s:.1f}s)\n"
    )
    for node_id, node_result in result.node_results.items():
        node_color = {"completed": "green", "failed": "red", "skipped": "yellow"}.get(
            node_result.status, "white"
        )
        console.print(f"  [{node_color}]{node_id}: {node_result.status}[/{node_color}]")
        if node_result.output:
            console.print(f"    {node_result.output[:300]}")

    summary = f"Pipeline '{pipeline_name}' {result.status}."
    app_state.messages.append({"role": "assistant", "content": summary})
    return result.status == "completed"


def handle_pipeline_command(app_state: AppState, user_input: str) -> None:
    pipeline_name, inputs = _parse_pipeline_command(user_input)
    run_pipeline(app_state, pipeline_name, inputs)


def handle_chat_input(app_state: AppState, user_input: str) -> None:
    app_state.messages.append({"role": "user", "content": user_input})

    try:
        response = app_state.pydantic_runtime.stream_text(
            user_input,
            message_history=app_state.pydantic_messages,
            on_text=_print_stream_chunk,
        )
        _track_tokens(response.usage)
        if response.messages:
            app_state.pydantic_messages.extend(response.messages)
        else:
            _append_pydantic_chat_exchange(app_state, user_input, response.content)
        app_state.messages.append({"role": "assistant", "content": response.content})
        _finish_stream_line(response.content)
    except sqlite3.OperationalError as exc:
        print_error(f"Database operation failed: {exc}")
    except (OSError, TypeError, ValueError, yaml.YAMLError) as exc:
        print_error(f"Tool execution failed: {exc}")


def _is_workflow_command(user_input: str) -> bool:
    return user_input.startswith(("workflow ", "/workflow "))


def _is_pipeline_command(user_input: str) -> bool:
    return user_input.startswith(("pipeline ", "/pipeline "))


def _parse_pipeline_command(user_input: str) -> tuple[str, dict[str, str]]:
    normalized = user_input.removeprefix("/").strip()
    parts = normalized.split(maxsplit=1)
    if len(parts) < MIN_PIPELINE_PARTS:
        return "", {}
    tokens = parts[1].split()
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
        console.print("No workflows found.")
        return
    for workflow_file in workflow_files:
        console.print(f"- {workflow_file.stem}")


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
        console.print(f"Unknown state command: {command}")
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
    console.print(f"Added session state {section}: {argument}")


def propose_state(app_state: AppState) -> None:
    proposal = app_state.database.create_state_proposal(app_state.session_id)
    console.print(f"Created state proposal: [cyan]{proposal.proposal_id}[/cyan]")
    print_markdown(proposal.payload.to_markdown("Proposed Project State Additions"))


def approve_state(app_state: AppState, proposal_id: str) -> None:
    if not proposal_id:
        next_state = app_state.database.approve_latest_proposal()
        print_markdown(next_state.to_markdown("Updated Project State"))
        return
    app_state.database.approve_state_proposal(proposal_id)
    console.print(f"Approved state proposal: {proposal_id}")


def reject_state(app_state: AppState, proposal_id: str) -> None:
    if not proposal_id:
        msg = "state reject requires a proposal_id"
        raise ValueError(msg)
    app_state.database.reject_state_proposal(proposal_id)
    console.print(f"Rejected state proposal: {proposal_id}")


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
    console.print(result.content)


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
    console.print(
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
        console.print(f"Unknown skill command: {command}")
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
        execute_named_skill(app_state, command, argument)
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


def is_skill_name(app_state: AppState, skill_name: str) -> bool:
    return skill_name in {
        tool["function"]["name"]
        for tool in app_state.skill_runner.discover_skills()
        if isinstance(tool.get("function"), dict) and isinstance(tool["function"].get("name"), str)
    }


def execute_named_skill(app_state: AppState, skill_name: str, argument: str) -> None:
    result = app_state.skill_runner.execute_skill(
        tool_name=skill_name,
        arguments=_parse_skill_arguments(app_state, skill_name, argument),
        session_id=app_state.session_id,
    )
    if result.content.lstrip().startswith("##"):
        print_markdown(result.content)
        return
    console.print(result.content)


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
    console.print(f"Created skill: [cyan]{scaffolded.skill_name}[/cyan]")
    for path in scaffolded.created_files:
        console.print(f"- {path.relative_to(app_state.config.project_root)}")


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
    console.print(
        """Skill commands:
  skill list
  skill show <name>
  skill create <name> <description>
  skill <name> [args|key=value|json-object]""",
        markup=False,
    )


def _print_stream_chunk(chunk: str) -> None:
    print(chunk, end="", flush=True)


def _finish_stream_line(content: str) -> None:
    if content:
        print()


# ------------------------------------------------------------------
# /goal command
# ------------------------------------------------------------------


def _is_goal_command(user_input: str) -> bool:
    return user_input.startswith(("/goal ", "goal "))


def handle_goal_command(app_state: AppState, user_input: str) -> None:
    objective = user_input.removeprefix("/").removeprefix("goal").strip()
    if not objective:
        console.print("Usage: /goal <objective>")
        return

    console.print("[cyan]Starting autonomous goal loop...[/cyan]")
    console.print(f"Goal: [bold]{objective}[/bold]")
    console.print()

    runner = GoalRunner()
    try:
        result = runner.run(
            goal=objective,
            app_state=app_state,
            on_text=_print_stream_chunk,
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

    console.print()
    console.print(f"[{color}]Status: {result.status}[/{color}]")
    console.print(f"Iterations: {result.iterations}")
    console.print(f"Total tokens: {result.total_tokens}")
    console.print()
    print_markdown(result.content)

    if result.events:
        console.print()
        console.print("[dim]--- Event Log ---[/dim]")
        for i, event in enumerate(result.events, 1):
            event_type = event.get("type", "?")
            tool = event.get("tool", "?")
            status = event.get("status", "")
            extra = f" ({status})" if status else ""
            console.print(f"[dim]{i}. [{event_type}] {tool}{extra}[/dim]")


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
    app_state.pydantic_messages.extend(
        [
            ModelRequest(parts=[UserPromptPart(content=user_content)]),
            ModelResponse(parts=[TextPart(content=assistant_content)]),
        ],
    )


def _build_prompt_bar(app_state: AppState) -> FormattedText:
    """Build a styled prompt bar showing model, reasoning, token usage, and cache."""
    llm = app_state.llm_client

    if llm.use_mock:
        return FormattedText(
            [
                ("fg:ansimagenta", "[mock]"),
                ("", " > "),
            ]
        )

    model = llm.model
    reasoning = llm.reasoning_effort
    thinking = llm.thinking

    parts: list[tuple[str, str]] = [
        ("fg:ansicyan", "["),
        ("fg:ansigreen bold", model),
    ]

    if thinking == "enabled":
        parts.append(("fg:ansiyellow", f" · reason:{reasoning}"))

    if _session_token_count > 0:
        token_text = _format_tokens(_session_token_count)
        if _session_cache_hit_tokens > 0:
            cached = _format_tokens(_session_cache_hit_tokens)
            token_text = f"{token_text} (cache {cached})"
        parts.append(("fg:ansiblue", f" · {token_text}"))

    parts.append(("fg:ansicyan", "]"))
    parts.append(("", " > "))

    return FormattedText(parts)


def _format_tokens(count: int) -> str:
    """Format a token count for compact display: 1200 -> '1.2k', 350 -> '350'."""
    if count >= TOKEN_MILLION:
        return f"{count / TOKEN_MILLION:.1f}M"
    if count >= TOKEN_THOUSAND:
        return f"{count / TOKEN_THOUSAND:.1f}k"
    return str(count)
