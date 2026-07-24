from __future__ import annotations

import json
import logging
import shlex
import sqlite3
import threading
from typing import TYPE_CHECKING, Any

import yaml
from pydantic_ai.messages import (
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
    GoalEvaluated,
    LLMActionEmitted,
    LLMTextEmitted,
    StreamPaused,
)
from harness_poc.core.observe import new_trace
from harness_poc.core.runtime import (
    AgentRunResult,
    GoalRunner,
    GoalRunResult,
    account_for_model_run,
    build_model,
    estimate_message_tokens,
    extract_observations_from_turn,
    prune_message_history,
    sanitize_new_messages,
    split_chat_turns,
)
from harness_poc.core.storage import build_state_context

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from pathlib import Path

    from pydantic_ai.messages import (
        ModelMessage,
    )

    from harness_poc.app_factory import AppState
    from harness_poc.core.runtime import (
        TokenAccounting,
    )
    from harness_poc.core.storage import StateSection
    from harness_poc.v2.wiring import V2Runtime


MIN_WORKFLOW_PARTS = 2
WORKFLOW_OBJECTIVE_PARTS = 2
MIN_PIPELINE_PARTS = 2

# Tools whose results carry structural signal worth extracting as observations.
_SIGNAL_TOOLS: frozenset[str] = frozenset(
    {
        "semble_search",
        "read_file",
        "search_files",
        "search_documents",
        "consolidate_state",
    }
)


def _track_tokens(accounting: TokenAccounting, app_state: AppState) -> None:
    app_state.streaming.session_tokens += accounting.new_tokens


def run_repl(app_state: AppState) -> None:
    from harness_poc.app_factory import bootstrap_document_index

    bootstrap_document_index(app_state.config, app_state.database)

    from harness_poc.tui import ChatApp

    ChatApp(app_state).run()


def handle_repl_input(app_state: AppState, user_input: str) -> None:  # noqa: PLR0911
    new_trace(app_state.session_id)
    logger.debug("REPL input: %s", user_input[:200])

    if _is_repl_help_command(user_input):
        print_repl_help()
        return

    if _is_mode_command(user_input):
        handle_mode_command(app_state, user_input)
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
    if _is_debug_command(user_input):
        handle_debug_command(app_state, user_input)
        return
    if _is_agents_command(user_input):
        handle_agents_command(app_state)
        return

    if _is_spawn_command(user_input):
        handle_spawn_command(app_state, user_input)
        return

    if _is_tasks_command(user_input):
        handle_tasks_command(app_state)
        return

    if _is_result_command(user_input):
        handle_result_command(app_state, user_input)
        return

    if _is_feed_command(user_input):
        handle_feed_command(app_state, user_input)
        return

    if _is_cancel_command(user_input):
        handle_cancel_command(app_state, user_input)
        return
    if _is_goal_command(user_input):
        handle_goal_command(app_state, user_input)
        return

    if _is_slice_command(user_input):
        handle_slice_command(app_state, user_input)
        return

    if _is_corpus_retrieval_command(user_input):
        handle_corpus_retrieval_command(app_state, user_input)
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
  /mode [chat|pipeline|react]
  /goal <objective>
  /spawn <persona> [bg] [--feed] <objective>
  /agents
  /tasks
  /result <task_id>
  /cancel <task_id>
  /feed <task_id>
  /slice <task_id>
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
  /debug [on|off]
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
    # Default + react + pipeline run the v2 event loop. `chat` is the explicit
    # native-streaming escape hatch (token-by-token, native pydantic-ai tools).
    if app_state.active_mode != "chat":
        _handle_v2_mode_input(app_state, user_input)
        return

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
    elif command == "events":
        show_state_events(app_state, argument)
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
  state consolidate [preview|propose|approve]
  state events [session_id] [limit]""",
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
            import subprocess

            content = msg["content"]
            try:
                subprocess.run(["pbcopy"], input=content.encode(), check=True)  # noqa: S607
                print_text("Last response copied to clipboard.")
            except FileNotFoundError, subprocess.CalledProcessError:
                print_text(content)
            return
    print_text("No response to copy.")


def _is_debug_command(user_input: str) -> bool:
    return user_input in {"/debug", "debug"} or user_input.startswith(("/debug ", "debug "))


def handle_debug_command(_app_state: AppState, user_input: str) -> None:
    """Toggle debug logging and console-to-log bridging.

    Usage: /debug on|off

    When on:
    - Enables DEBUG-level logging for distiller, materializer, skill-runner,
      pydantic-runtime, event-bus, and repl.console loggers.
    - Debug output routes to the harness log file (no stderr — won't corrupt the TUI).
    - Enables LogTap: all print_text/print_error/print_markdown output is
      duplicated to the log file for session replay.
    """
    import logging

    from harness_poc.core.observe import get_log_tap

    parts = user_input.strip().split(maxsplit=1)
    target = parts[1].strip().lower() if len(parts) > 1 else ""

    loggers = [
        "harness_poc.core.context_map.distiller",
        "harness_poc.core.runtime.pydantic_runtime",
        "harness_poc.core.skills.skill_runner",
        "harness_poc.core.events.event_bus",
        "harness_poc.core.events.event_store",
        "harness_poc.repl.console",
        "skills.context-map-materializer",
    ]

    if target in ("on", "1", "true"):
        _ensure_stderr_handler()
        for name in loggers:
            logging.getLogger(name).setLevel(logging.DEBUG)
        get_log_tap().enabled = True
        print_text(
            "[bold green]Debug logging ON[/bold green] — "
            "distiller timing, LLM tokens, skill duration, console-to-log"
        )
    elif target in ("off", "0", "false"):
        for name in loggers:
            logging.getLogger(name).setLevel(logging.NOTSET)
        get_log_tap().enabled = False
        print_text("[dim]Debug logging OFF[/dim]")
    else:
        print_text("Usage: [bold]/debug on|off[/bold]")


def _ensure_stderr_handler() -> None:
    """Ensure debug log output goes to the harness log file.

    The RotatingFileHandler from configure_logging is always present,
    so this is a no-op — DEBUG messages already route to the file.
    Stderr is intentionally avoided because it corrupts the TUI display.
    """


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
# /agents command
# ------------------------------------------------------------------


def _is_agents_command(user_input: str) -> bool:
    return user_input in {"/agents", "agents"}


# ------------------------------------------------------------------
# /spawn command
# ------------------------------------------------------------------


def _is_spawn_command(user_input: str) -> bool:
    return user_input.startswith(("/spawn ", "spawn "))


def _parse_spawn_command(user_input: str) -> tuple[str, str, bool, bool]:
    """Parse "/spawn <persona> [bg] [--feed] <objective>" into (persona, objective, background, feed)."""
    normalized = user_input.removeprefix("/").removeprefix("spawn").strip()
    parts = normalized.split(maxsplit=1)
    if not parts or not parts[0]:
        return ("", "", False, False)
    persona = parts[0]
    if len(parts) < 2:
        return (persona, "", False, False)
    rest = parts[1]
    background = False
    feed = False
    if rest.startswith("bg "):
        background = True
        rest = rest[3:]
    elif rest == "bg":
        return (persona, "", True, False)
    # Check for --feed flag (position-independent after bg)
    if rest.startswith("--feed ") or rest == "--feed":
        feed = True
        rest = rest[7:] if rest.startswith("--feed ") else ""
    elif " --feed" in rest:
        idx = rest.index(" --feed")
        rest = rest[:idx] + rest[idx + 7 :]
        feed = True
    return (persona, rest.strip(), background, feed)


# ------------------------------------------------------------------
# /tasks command
# ------------------------------------------------------------------


def _is_tasks_command(user_input: str) -> bool:
    return user_input in {"/tasks", "tasks"}


# ------------------------------------------------------------------
# /result command
# ------------------------------------------------------------------


def _is_result_command(user_input: str) -> bool:
    return user_input.startswith(("/result ", "result "))


def _parse_result_command(user_input: str) -> str:
    """Extract task_id from \"/result <task_id>\"."""
    normalized = user_input.removeprefix("/").removeprefix("result").strip()
    return normalized


def _get_engine(app_state: AppState):
    if app_state.v2_runtime and app_state.v2_runtime.execution_engine:
        return app_state.v2_runtime.execution_engine
    print_error(
        "Sub-agent engine not available in chat mode. Use /mode pipeline or /mode react first."
    )
    return None


def _persona_names(app_state: AppState) -> list[str]:
    """Return sorted persona names from the personas/ directory."""
    personas_dir = app_state.config.project_root / "personas"
    if not personas_dir.is_dir():
        return []
    return sorted(p.stem for p in personas_dir.glob("*.md"))


def handle_agents_command(app_state: AppState) -> None:
    """List available persona names from personas/."""
    names = _persona_names(app_state)
    if not names:
        print_text("[dim]No personas found in personas/[/dim]")
        return
    print_text("[bold]Available personas:[/bold]")
    for name in names:
        print_text(f"  {name}")


def handle_spawn_command(app_state: AppState, user_input: str) -> None:
    """Spawn a sub-agent: /spawn <persona> [bg] [--feed] <objective>."""
    engine = _get_engine(app_state)
    if engine is None:
        return

    persona, objective, background, feed = _parse_spawn_command(user_input)
    if not persona:
        print_text("Usage: /spawn <persona> [bg] [--feed] <objective>")
        return
    if not objective:
        print_text("Usage: /spawn <persona> [bg] [--feed] <objective>")
        return

    valid = _persona_names(app_state)
    if valid and persona not in valid:
        print_error(f"Unknown persona '{persona}'. Available: {', '.join(valid)}")
        return

    mode = "background" if background else "foreground"

    if not background:
        print_text(f"[dim]Spawning [bold]{persona}[/bold] — {objective}[/dim]")

    try:
        result = engine.spawn_sub_agent(
            agent_type=persona,
            task_payload={"objective": objective},
            mode=mode,
            session_id=app_state.session_id,
        )
    except Exception as exc:
        print_error(f"Spawn failed: {exc}")
        return

    _print_spawn_result(result, persona, background)

    if feed and not background:
        _feed_task_to_chat(app_state, result["task_id"])
    elif feed:
        print_text(
            "[dim]Use [bold]/feed" + f" {result['task_id']}[/bold]"
            " to inject findings into chat when ready.[/dim]"
        )


def _print_spawn_result(result: dict[str, Any], persona: str, background: bool) -> None:
    """Format and print a spawn_sub_agent result dict."""
    task_id = result.get("task_id", "?")
    label = result.get("output_label", "?")
    summary = result.get("summary", "")
    raw = result.get("raw_output", "")

    if background:
        print_text(
            f"[bold]Queued[/bold] background task [cyan]{task_id}[/cyan] ([bold]{persona}[/bold])"
        )
        if summary:
            print_text(f"  {summary}")
        return

    # Foreground result
    color = "green" if label == "completed" else "red"
    print_text(f"[bold]{persona}[/bold] finished: [{color}]{label}[/{color}] ({task_id})")

    # Format and render the actual output as markdown
    formatted = _format_raw_output(raw)
    if formatted:
        print_markdown(formatted)
    elif summary:
        print_markdown(summary)


def _format_raw_output(raw: Any) -> str:
    """Parse raw output into a human-readable markdown string.

    If raw is a JSON object with recognizable keys, extract and format
    them nicely. Falls back to a plain code block for unparseable content.
    """
    if raw is None or raw == "":
        return ""

    # Try JSON parse
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError, TypeError:
            # Plain text — display in a code block, truncated
            truncated = str(raw)[:3000]
            if len(str(raw)) > 3000:
                truncated += "\n... (truncated)"
            return f"```\n{truncated}\n```"
    else:
        parsed = raw

    # If parsed is a dict with known fields, format them
    if isinstance(parsed, dict):
        return _format_parsed_dict(parsed)

    # If it's a list, format each item
    if isinstance(parsed, list):
        parts: list[str] = []
        for item in parsed:
            if isinstance(item, dict):
                parts.append(_format_parsed_dict(item))
            else:
                parts.append(str(item)[:500])
        return "\n\n".join(parts)

    # Fallback
    return f"```\n{str(parsed)[:3000]}\n```"


def _format_parsed_dict(data: dict[str, Any]) -> str:
    """Format a parsed JSON dict into readable markdown sections."""
    lines: list[str] = []

    # Display named fields in a consistent order
    _field = lambda key, label=None: (
        lines.append(f"**{label or key}:** {data[key]}") if data.get(key) else None
    )

    _field("text")
    _field("output")
    _field("result")
    _field("content")
    _field("summary", "Result")
    _field("response")
    _field("error", "Error")

    # Any remaining fields not individually handled
    handled = {"text", "output", "result", "content", "summary", "response", "error"}
    for key, value in data.items():
        if key in handled:
            continue
        if value is None or value == "":
            continue
        val_str = str(value)
        if len(val_str) > 200:
            val_str = val_str[:200] + "..."
        lines.append(f"**{key}:** {val_str}")

    return "\n".join(lines) if lines else f"```\n{json.dumps(data, indent=2)[:3000]}\n```"


def handle_tasks_command(app_state: AppState) -> None:
    """List background sub-agent tasks."""
    engine = _get_engine(app_state)
    if engine is None:
        return

    tasks = engine.list_tasks()
    if not tasks:
        print_text("[dim]No background tasks.[/dim]")
        return

    print_text("[bold]Background tasks:[/bold]")
    for task_id, info in sorted(tasks.items()):
        status = info.get("status", "?")
        persona = info.get("persona", "?")
        summary = info.get("summary", "")[:80]
        color = {"running": "yellow", "done": "green", "cancelled": "red"}.get(status, "white")
        print_text(f"  [{color}]{task_id}[/{color}]  {persona:12s}  {status:10s}  {summary}")


def handle_result_command(app_state: AppState, user_input: str) -> None:
    """Retrieve and display a completed background task result."""
    engine = _get_engine(app_state)
    if engine is None:
        return

    task_id = _parse_result_command(user_input)
    if not task_id:
        print_text("Usage: /result <task_id>")
        return

    try:
        result = engine.result(task_id)
    except Exception as exc:
        print_error(str(exc))
        return

    persona = result.get("metadata", {}).get("agent_type", "unknown")
    _print_spawn_result(result, persona, background=True)
    print_text(f"[dim]Task {task_id} removed from pool.[/dim]")


def handle_cancel_command(app_state: AppState, user_input: str) -> None:
    """Cancel a running background sub-agent."""
    engine = _get_engine(app_state)
    if engine is None:
        return

    task_id = _parse_cancel_command(user_input)
    if not task_id:
        print_text("Usage: /cancel <task_id>")
        return

    try:
        cancelled = engine.cancel(task_id)
    except Exception as exc:
        print_error(str(exc))
        return

    if cancelled:
        print_text(f"Cancelled task [cyan]{task_id}[/cyan].")
    else:
        print_text(f"Task [cyan]{task_id}[/cyan] is already done or cancelled.")


def _is_cancel_command(user_input: str) -> bool:
    return user_input.startswith(("/cancel ", "cancel "))


def _parse_cancel_command(user_input: str) -> str:
    """Extract task_id from \"/cancel <task_id>\"."""
    normalized = user_input.removeprefix("/").removeprefix("cancel").strip()
    return normalized


def _is_goal_command(user_input: str) -> bool:
    return user_input.startswith(("/goal ", "goal "))


# ------------------------------------------------------------------
# /feed command
# ------------------------------------------------------------------


def _is_feed_command(user_input: str) -> bool:
    return user_input.startswith(("/feed ", "feed "))


def _parse_feed_command(user_input: str) -> str:
    """Extract task_id from "/feed <task_id>"."""
    normalized = user_input.removeprefix("/").removeprefix("feed").strip()
    return normalized


def handle_feed_command(app_state: AppState, user_input: str) -> None:
    """Inject a completed sub-agent result into chat history."""
    task_id = _parse_feed_command(user_input)
    if not task_id:
        print_text("Usage: /feed <task_id>")
        return

    _feed_task_to_chat(app_state, task_id)


def _feed_task_to_chat(app_state: AppState, task_id: str) -> None:
    """Read a DelegatedTaskOutput from the blackboard and append to chat history."""
    key = f"delegated:{task_id}"
    try:
        value = app_state.database.read_memory(app_state.session_id, key)
    except Exception:
        print_error(f"Failed to read blackboard for task {task_id}.")
        return

    if value is None:
        print_error(f"No result found for task [cyan]{task_id}[/cyan].")
        return

    # value is a dict with keys: task_id, output_label, summary, raw_output, metadata
    if not isinstance(value, dict):
        print_error(f"Task {task_id} has no feed-able output.")
        return

    persona = (value.get("metadata", {}) or {}).get("agent_type", "unknown")
    raw = value.get("raw_output", "")
    summary = value.get("summary", "")

    formatted = _format_raw_output(raw) if raw else (summary or "(no output)")
    # Marker prefix enables /slice to find and remove this message later.
    content = (
        f"<!--fed:{task_id}-->\n"
        f"Sub-agent findings from [bold]{persona}[/bold] (task {task_id}):\n\n{formatted}"
    )

    # Append as synthetic user message to pydantic_messages chat history
    _inject_context_message(app_state, content)

    print_text(f"Fed [bold]{persona}[/bold] findings (task [cyan]{task_id}[/cyan]) to chat.")


def _inject_context_message(app_state: AppState, content: str) -> None:
    """Append a synthetic user message with injected context into pydantic_messages."""
    from pydantic_ai.messages import ModelRequest, TextPart

    msg = ModelRequest(parts=[TextPart(content=content)])
    app_state.pydantic_messages.append(msg)
    # Bound to prevent unbounded growth from repeated feeds
    try:
        app_state.pydantic_messages = _bounded_pydantic_messages(app_state)
    except AttributeError:
        pass  # config.runtime not available in some test contexts


# ------------------------------------------------------------------
# /slice command
# ------------------------------------------------------------------


def _is_slice_command(user_input: str) -> bool:
    return user_input.startswith(("/slice ", "slice "))


def _parse_slice_command(user_input: str) -> str:
    """Extract task_id from "/slice <task_id>"."""
    normalized = user_input.removeprefix("/").removeprefix("slice").strip()
    return normalized


FEED_MARKER_PREFIX = "<!--fed:"
FEED_MARKER_SUFFIX = "-->"


def handle_slice_command(app_state: AppState, user_input: str) -> None:
    """Remove a previously-fed sub-agent result from chat history."""
    task_id = _parse_slice_command(user_input)
    if not task_id:
        print_text("Usage: /slice <task_id>")
        return

    marker = f"{FEED_MARKER_PREFIX}{task_id}{FEED_MARKER_SUFFIX}"
    removed = 0
    kept: list[ModelMessage] = []

    for msg in app_state.pydantic_messages:
        if _message_contains_marker(msg, marker):
            removed += 1
        else:
            kept.append(msg)

    app_state.pydantic_messages[:] = kept

    if removed:
        print_text(
            f"Sliced {removed} message(s) for task [cyan]{task_id}[/cyan] from chat history."
        )
    else:
        print_text(f"No fed messages found for task [cyan]{task_id}[/cyan].")


def _message_contains_marker(msg: object, marker: str) -> bool:
    """Check if a pydantic_ai ModelMessage contains the given marker string."""
    for part in getattr(msg, "parts", []):
        if hasattr(part, "content") and marker in getattr(part, "content", ""):
            return True
    return False


# ------------------------------------------------------------------
# /corpus-retrieval command
# ------------------------------------------------------------------


def _is_corpus_retrieval_command(user_input: str) -> bool:
    return user_input.startswith(("/corpus-retrieval", "corpus-retrieval "))


def handle_corpus_retrieval_command(app_state: AppState, user_input: str) -> None:
    """Toggle cross-corpus retrieval mode: /corpus-retrieval [semantic|deterministic]."""
    normalized = user_input.removeprefix("/").removeprefix("corpus-retrieval").strip()
    if not normalized:
        current = app_state.runtime.pydantic_runtime.deps.retrieval_mode[0]
        print_text(f"Active retrieval mode: [bold]{current}[/bold]")
        return
    mode = normalized.lower()
    if mode not in ("semantic", "deterministic"):
        print_text("Usage: /corpus-retrieval [semantic|deterministic]")
        return
    app_state.runtime.pydantic_runtime.deps.retrieval_mode[0] = mode
    print_text(f"Retrieval mode set to: [bold]{mode}[/bold]")


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


# ---------------------------------------------------------------------------
# Mode switching (v2 pipeline / react / chat)
# ---------------------------------------------------------------------------

VALID_MODES = frozenset({"chat", "pipeline", "react"})


def _is_mode_command(user_input: str) -> bool:
    return user_input.startswith(("/mode", "mode ")) or user_input in {"/mode", "mode"}


def handle_mode_command(app_state: AppState, user_input: str) -> None:
    parts = user_input.removeprefix("/").removeprefix("mode").strip().split(maxsplit=1)
    if not parts or parts == [""]:
        print_text(f"Active mode: [bold]{app_state.active_mode}[/bold]")
        return

    new_mode = parts[0].lower()
    if new_mode not in VALID_MODES:
        print_error(f"Unknown mode '{new_mode}'. Valid modes: {', '.join(sorted(VALID_MODES))}")
        return

    if new_mode == app_state.active_mode:
        print_text(f"Already in [bold]{new_mode}[/bold] mode.")
        return

    app_state.active_mode = new_mode

    if new_mode != "chat" and app_state.v2_runtime is None:
        from harness_poc.v2.wiring import build_v2_runtime

        app_state.v2_runtime = build_v2_runtime(app_state.identity, app_state.config, mode=new_mode)

    print_text(f"Switched to [bold]{new_mode}[/bold] mode.")


def _handle_v2_mode_input(app_state: AppState, user_input: str) -> None:
    """Handle a plain-text input when active_mode is pipeline or react."""
    mode = app_state.active_mode
    if app_state.v2_runtime is None:
        from harness_poc.v2.wiring import build_v2_runtime

        app_state.v2_runtime = build_v2_runtime(
            app_state.identity, app_state.config, mode=mode
        )
    runtime = app_state.v2_runtime

    print_text(f"[cyan]Running {mode} mode...[/cyan]")
    print_text(f"Objective: [bold]{user_input}[/bold]")
    print_text("")

    if mode == "pipeline":
        _run_pipeline_inline(app_state, runtime, user_input)
    elif mode == "react":
        _run_react_inline(app_state, runtime, user_input)


def _run_pipeline_inline(app_state: AppState, runtime: V2Runtime, user_input: str) -> None:
    """Run the pipeline synchronously (blocks REPL until done)."""
    from harness_poc.core.events import ExecutionCompleted, GateCompleted, ProbeCompleted

    orch = runtime.orchestrator
    if orch is None:
        print_error("Pipeline orchestrator not available")
        return
    bus = runtime.bus

    def on_probe(event: ProbeCompleted) -> None:
        if event.success:
            print_text("  Probe: PASSED")
        else:
            print_text(f"  Probe: FAILED — {len(event.constraints)} constraint(s)")

    def on_execution(event: ExecutionCompleted) -> None:
        agents = event.sub_agents
        if not agents:
            print_text("  Execution: skipped (no tasks)")
        elif event.all_passed:
            print_text(f"  Execution: PASSED — {len(agents)} agent(s)")
        else:
            failed = sum(1 for a in agents if a.get("output_label") != "completed")
            print_text(f"  Execution: FAILED — {failed}/{len(agents)} agent(s)")

    def on_gate(event: GateCompleted) -> None:
        if event.passed:
            print_text(f"  Gate: PASSED — {event.test_count} test(s)")
        else:
            print_text(f"  Gate: FAILED — {event.test_count} test(s)")
        print_text("  Done.")

    bus.subscribe(ProbeCompleted, on_probe)
    bus.subscribe(ExecutionCompleted, on_execution)
    bus.subscribe(GateCompleted, on_gate)

    orch.run_pipeline_via_bus(
        spec={"goal": user_input, "tasks": []},
        persona_id="coder",
        probe_code=None,
        workspace_path=None,
        session_id=app_state.session_id,
    )


def _run_react_inline(app_state: AppState, runtime: V2Runtime, user_input: str) -> None:
    """Run the ReAct loop in a background thread so the REPL stays responsive."""
    import asyncio
    import threading

    session_id = app_state.session_id
    bus = runtime.bus
    output_parts: list[str] = []
    # Drive the shared streaming seam so output renders in both surfaces: the
    # REPL's default callbacks print to the console; the TUI's callbacks render
    # into chat widgets and on_finish clears the "worker running" state.
    # ponytail: react LlmWorker uses run_text, so on_text fires once (not
    # token-streamed); tool events aren't forwarded to the TUI tool panel yet.
    streaming = app_state.streaming

    def _run() -> None:
        terminal_event = asyncio.Event()

        def on_text(event: LLMTextEmitted) -> None:
            output_parts.append(event.content)
            streaming.on_text(event.content)
            terminal_event.set()

        def on_pause(_event: StreamPaused) -> None:
            terminal_event.set()

        def on_goal(_event: GoalEvaluated) -> None:
            terminal_event.set()

        bus.subscribe(LLMTextEmitted, on_text)
        bus.subscribe(StreamPaused, on_pause)
        bus.subscribe(GoalEvaluated, on_goal)

        async def _react() -> None:
            await runtime.start(session_id)
            try:
                bus.publish(AgentInputAdded(session_id=session_id, user_content=user_input))
                await asyncio.wait_for(terminal_event.wait(), timeout=120.0)
            except TimeoutError:
                output_parts.append("Time budget exhausted.")
            finally:
                await runtime.stop(session_id)

        asyncio.run(_react())

    thread = threading.Thread(target=_run, daemon=True, name="react-repl-runner")
    thread.start()
    thread.join(timeout=130.0)

    if not output_parts:
        streaming.on_text("ReAct loop completed (no text output).")
    streaming.on_finish("\n".join(output_parts).strip())


def show_state_events(app_state: AppState, argument: str) -> None:
    """Display recent state events, optionally filtered by session ID."""
    limit = 50
    args = argument.strip().split()
    session_filter: str | None = None
    for arg in args:
        if arg.isdigit():
            limit = min(int(arg), 200)
        else:
            session_filter = arg
    events = app_state.database.list_state_events(
        session_id=session_filter,
        limit=limit,
    )
    if not events:
        print_text("No state events found.")
        return
    for e in reversed(events):
        scope_label = e["scope"][:4].upper()  # SESS or PROJ
        print_text(
            f"[dim]{e['created_at']}[/dim] "
            f"[{scope_label}] {e['event_type']} "
            f"[dim]{_event_detail(e)}[/dim]"
        )


def _event_detail(event: dict) -> str:
    """Extract a short human-readable detail from a state event payload."""
    inner = event.get("payload", {})
    if not isinstance(inner, dict):
        return ""
    detail = inner.get("payload", {})
    if not isinstance(detail, dict):
        return ""
    if "text" in detail:
        return str(detail["text"])[:60]
    if "key" in detail:
        return f"{detail['key']}={detail.get('value', '')}"
    if "proposal_id" in detail:
        return str(detail["proposal_id"])[:8]
    return ""
