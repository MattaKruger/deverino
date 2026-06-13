from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, cast

import typer
from rich.table import Table

from harness_poc.app_factory import STARTUP_ERRORS, AppState, build_app_state
from harness_poc.console import console, print_error, print_text
from harness_poc.core.acdl.cli import acdl_app
from harness_poc.core.config import HarnessConfig
from harness_poc.core.events import (
    AgentInputAdded,
    BaseEvent,
    GoalEvaluated,
    LLMActionEmitted,
    LLMTextEmitted,
    SkillCompleted,
    SkillRequested,
    StreamPaused,
    fetch_event_log_rows,
    fetch_latest_event_log_rows,
    render_event_log_row,
)
from harness_poc.core.observability import (
    DashboardSnapshot,
    fetch_dashboard_snapshot,
    snapshot_to_dict,
)
from harness_poc.core.processors.circuit_breaker import run_circuit_breaker
from harness_poc.core.processors.llm_worker import run_llm_worker
from harness_poc.core.processors.tool_worker import run_skill_worker
from harness_poc.core.runtime import GoalRunResult
from harness_poc.core.storage import BlackboardDatabase
from harness_poc.repl import (
    append_session_state,
    approve_state,
    consolidate_state,
    create_skill,
    list_skills,
    propose_state,
    reject_state,
    run_repl,
    run_workflow,
    show_skill,
    show_state,
)
from harness_poc.v2.runtime import V2Runtime

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy import Engine


@dataclass(frozen=True, slots=True)
class EventLogOptions:
    engine: Engine
    session_id: str | None
    event_types: list[str]
    since_id: int | None
    limit: int
    follow: bool
    poll_interval: float
    json_output: bool
    include_payload: bool


app = typer.Typer(
    name="harness-poc",
    help="Interactive LLM harness proof of concept.",
    rich_markup_mode="rich",
    invoke_without_command=True,
    no_args_is_help=False,
    pretty_exceptions_show_locals=False,
)
workflow_app = typer.Typer(
    help="Run deterministic workflow YAML files.",
    rich_markup_mode="rich",
)
state_app = typer.Typer(
    help="Manage durable project and session state.",
    rich_markup_mode="rich",
)
skill_app = typer.Typer(
    help="Manage executable skills.",
    rich_markup_mode="rich",
)
tool_app = typer.Typer(
    help="Manage built-in tools (LLM-callable primitives).",
    rich_markup_mode="rich",
)
documents_app = typer.Typer(
    help="Index and search project documents.",
    rich_markup_mode="rich",
)
pipeline_app = typer.Typer(
    help="Run declarative DAG pipeline YAML files.",
    rich_markup_mode="rich",
)
dashboard_app = typer.Typer(
    help="Run lightweight local dashboards over harness events.",
    rich_markup_mode="rich",
)
cartographer_app = typer.Typer(
    help="Manage the Deterministic Cartographer.",
    rich_markup_mode="rich",
)
v2_app = typer.Typer(
    help="V2 engine operations — probe, gate, workflow.",
    rich_markup_mode="rich",
)


@app.callback(invoke_without_command=True)
def main_callback(
    ctx: typer.Context,
    resume: Annotated[
        str | None,
        typer.Option("--resume", help="Resume session by id."),
    ] = None,
    resume_last: Annotated[  # noqa: FBT002
        bool,
        typer.Option("--resume-last", help="Resume the most recent session."),
    ] = False,
    corpus: Annotated[
        str | None,
        typer.Option(
            "--corpus", "-c",
            help=(
                "Active corpus key for new sessions (default: "
                "<project_id>:codebase). Must contain ':'. Unknown keys "
                "warn but are allowed so the agent can bootstrap them."
            ),
        ),
    ] = None,
) -> None:
    """Interactive LLM harness proof of concept."""
    if ctx.invoked_subcommand is not None:
        return
    resolved_corpus = _validate_corpus(corpus)
    app_state = _new_app_state(
        session_id=_resolve_resume(resume, resume_last),
        corpus_key=resolved_corpus,
    )
    run_repl(app_state)
    raise typer.Exit


@app.command()
def repl(
    resume: Annotated[
        str | None,
        typer.Option("--resume", help="Resume session by id."),
    ] = None,
    resume_last: Annotated[  # noqa: FBT002
        bool,
        typer.Option("--resume-last", help="Resume the most recent session."),
    ] = False,
    corpus: Annotated[
        str | None,
        typer.Option(
            "--corpus", "-c",
            help=(
                "Active corpus key for new sessions (default: "
                "<project_id>:codebase). Must contain ':'. Unknown keys "
                "warn but are allowed so the agent can bootstrap them."
            ),
        ),
    ] = None,
) -> None:
    """Start the interactive REPL."""
    resolved_corpus = _validate_corpus(corpus)
    app_state = _new_app_state(
        session_id=_resolve_resume(resume, resume_last),
        corpus_key=resolved_corpus,
    )
    run_repl(app_state)


@app.command("run")
def run_command(
    objective: Annotated[
        str,
        typer.Argument(help="The goal/spec to execute."),
    ],
    mode: Annotated[
        str,
        typer.Option(
            "--mode", "-m",
            help="Execution mode: 'pipeline' (default) or 'react'.",
        ),
    ] = "pipeline",
    persona: Annotated[
        str,
        typer.Option("--persona", "-p", help="Persona to use (e.g. coder, reviewer)."),
    ] = "coder",
    spec_file: Annotated[
        str | None,
        typer.Option("--spec", "-s", help="Path to a YAML spec file (pipeline mode)."),
    ] = None,
    max_iterations: Annotated[
        int,
        typer.Option(
            "--max-iterations", "-n",
            help="Max loop iterations (react mode, default 50).",
        ),
    ] = 50,
    max_seconds: Annotated[
        float | None,
        typer.Option(
            "--max-seconds", "-t",
            help="Max wall-clock seconds (react mode).",
        ),
    ] = None,
    max_tokens: Annotated[
        int | None,
        typer.Option(
            "--max-tokens", "-k",
            help="Max cumulative tokens (react mode).",
        ),
    ] = None,
) -> None:
    """Run a v2 workflow or ReAct loop with mode selection.

    Examples:
        harness-poc run --mode pipeline "implement a test"
        harness-poc run --mode react "write a function"
    """
    app_state = _new_app_state(mode=mode)
    _run_command(
        lambda: _run_v2_mode(
            app_state,
            objective=objective,
            mode=mode,
            persona=persona,
            spec_file=spec_file,
            max_iterations=max_iterations,
            max_seconds=max_seconds,
            max_tokens=max_tokens,
        )
    )


def _resolve_resume(resume: str | None, resume_last: bool) -> str | None:  # noqa: FBT001
    if resume:
        return resume
    if resume_last:
        config = HarnessConfig.load()
        from harness_poc.core.storage import create_db_engine  # noqa: PLC0415

        db = BlackboardDatabase(create_db_engine(config.runtime.database_url))
        db.create_tables()
        last = db.get_last_session_id()
        if last is None:
            print_error("No prior sessions found.")
            raise typer.Exit(code=1)
        return last
    return None


def _validate_corpus(corpus: str | None) -> str | None:
    if corpus is None:
        return None
    corpus = corpus.strip()
    if ":" not in corpus:
        print_error(
            f"--corpus value {corpus!r} must follow 'project:name' form.",
        )
        raise typer.Exit(1)

    # Soft warning, not a hard fail — unknown keys are allowed so the agent
    # can bootstrap a new corpus by observing into it.
    config = HarnessConfig.load()
    from harness_poc.core.storage import create_db_engine  # noqa: PLC0415

    db = BlackboardDatabase(create_db_engine(config.runtime.database_url))
    db.create_tables()
    if corpus not in set(db.get_all_corpus_keys()):
        console.print(
            f"[yellow]Note:[/yellow] corpus {corpus!r} not found in the "
            f"blackboard yet — it will materialize after the first observe.",
        )
    return corpus


@workflow_app.command("run")
def workflow_run(
    name: Annotated[str, typer.Argument(help="Workflow YAML name without .yaml.")],
    objective: Annotated[str, typer.Argument(help="Objective passed to the workflow.")],
) -> None:
    """Run a workflow once and exit."""
    app_state = _new_app_state()
    if not run_workflow(app_state, name, objective):
        raise typer.Exit(1)


@state_app.command("show")
def state_show(
    scope: Annotated[
        str,
        typer.Argument(help="State scope: project, session, or all."),
    ] = "all",
) -> None:
    """Show project, session, or combined state."""
    app_state = _new_app_state()
    _run_command(lambda: show_state(app_state, scope))


@state_app.command("note")
def state_note(
    text: Annotated[str, typer.Argument(help="Note text to add to session state.")],
) -> None:
    """Add a note to the current one-shot session state."""
    _append_state("note", text)


@state_app.command("decision")
def state_decision(
    text: Annotated[str, typer.Argument(help="Decision text to add to session state.")],
) -> None:
    """Add a decision to the current one-shot session state."""
    _append_state("decision", text)


@state_app.command("next")
def state_next(
    text: Annotated[str, typer.Argument(help="Next action to add to session state.")],
) -> None:
    """Add a next action to the current one-shot session state."""
    _append_state("next", text)


@state_app.command("question")
def state_question(
    text: Annotated[
        str,
        typer.Argument(help="Open question to add to session state."),
    ],
) -> None:
    """Add an open question to the current one-shot session state."""
    _append_state("question", text)


@state_app.command("changelog")
def state_changelog(
    entry: Annotated[
        str,
        typer.Argument(help="Changelog entry to add to session state."),
    ],
) -> None:
    """Add a changelog entry to the current one-shot session state."""
    _append_state("changelog", entry)


@state_app.command("propose")
def state_propose() -> None:
    """Create a project-state proposal from the current one-shot session."""
    app_state = _new_app_state()
    _run_command(lambda: propose_state(app_state))


@state_app.command("approve")
def state_approve(
    proposal_id: Annotated[
        str | None,
        typer.Argument(help="Proposal id. If omitted, approves latest pending proposal."),
    ] = None,
) -> None:
    """Approve a pending project-state proposal."""
    app_state = _new_app_state()
    _run_command(lambda: approve_state(app_state, proposal_id or ""))


@state_app.command("reject")
def state_reject(
    proposal_id: Annotated[str, typer.Argument(help="Proposal id to reject.")],
) -> None:
    """Reject a pending project-state proposal."""
    app_state = _new_app_state()
    _run_command(lambda: reject_state(app_state, proposal_id))


@state_app.command("consolidate")
def state_consolidate(
    mode: Annotated[
        str,
        typer.Argument(help="Consolidation mode: preview, propose, or approve."),
    ] = "preview",
) -> None:
    """Preview, propose, or approve consolidation of the current session state."""
    app_state = _new_app_state()
    _run_command(lambda: consolidate_state(app_state, mode))


@skill_app.command("list")
def skill_list() -> None:
    """List discovered system and project skills."""
    app_state = _new_app_state()
    _run_command(lambda: list_skills(app_state))


@tool_app.command("list")
def tool_list() -> None:
    """List built-in tools (LLM-callable primitives)."""
    app_state = _new_app_state()
    _run_command(lambda: _list_tools(app_state))


@skill_app.command("show")
def skill_show(
    name: Annotated[str, typer.Argument(help="Skill directory/name to display.")],
) -> None:
    """Show a skill document."""
    app_state = _new_app_state()
    _run_command(lambda: show_skill(app_state, name))


@skill_app.command("create")
def skill_create(
    name: Annotated[str, typer.Argument(help="New skill name.")],
    description: Annotated[str, typer.Argument(help="New skill description.")],
) -> None:
    """Scaffold a project-local skill."""
    app_state = _new_app_state()
    _run_command(lambda: create_skill(app_state, f"{name} {description}"))


@documents_app.command("index")
def documents_index(
    paths: Annotated[
        list[str],
        typer.Argument(help="Document files or directories to index, relative to project root."),
    ],
    glob_pattern: Annotated[
        str,
        typer.Option(
            "--glob",
            help="Glob pattern used when a path is a directory.",
        ),
    ] = "**/*",
    force: Annotated[  # noqa: FBT002
        bool,
        typer.Option(
            "--force",
            "-f",
            help="Reindex sources even when their content hash is unchanged.",
        ),
    ] = False,
    exclude_dirs: Annotated[
        list[str] | None,
        typer.Option(
            "--exclude-dir",
            help="Directory to skip while indexing. May be provided more than once.",
        ),
    ] = None,
) -> None:
    """Index project documents into Vespa retrieval."""
    app_state = _new_app_state()
    _run_command(
        lambda: _index_documents(
            app_state,
            paths,
            glob_pattern,
            exclude_dirs=exclude_dirs or [],
            force=force,
        )
    )


@app.command()
def goal(
    objective: Annotated[str, typer.Argument(help="The goal to pursue autonomously.")],
    max_iterations: Annotated[
        int,
        typer.Option(
            "--max-iterations",
            "-n",
            help="Max loop iterations before budget exhaustion (default 50).",
        ),
    ] = 50,
    max_seconds: Annotated[
        float | None,
        typer.Option(
            "--max-seconds",
            "-t",
            help="Max wall-clock seconds before budget exhaustion.",
        ),
    ] = None,
    max_tokens: Annotated[
        int | None,
        typer.Option(
            "--max-tokens",
            "-k",
            help="Max cumulative input+output tokens before budget exhaustion.",
        ),
    ] = None,
) -> None:
    """Run an autonomous event-sourced goal execution loop."""
    app_state = _new_app_state()
    try:
        from harness_poc.app_factory import bootstrap_document_index  # noqa: PLC0415

        bootstrap_document_index(app_state.config, app_state.database)

        result = asyncio.run(
            _run_event_sourced_goal(
                objective=objective,
                app_state=app_state,
                max_iterations=max_iterations,
                max_seconds=max_seconds,
                max_tokens=max_tokens,
            )
        )
    except Exception as exc:
        logger.exception(
            "CLI goal command failed",
            extra={"session_id": app_state.session_id, "objective": objective},
        )
        print_error(f"Goal loop failed: {exc}")
        raise typer.Exit(1) from exc

    _print_goal_cli_result(result)


async def _run_event_sourced_goal(
    *,
    objective: str,
    app_state: AppState,
    max_iterations: int,
    max_seconds: float | None,
    max_tokens: int | None,
) -> GoalRunResult:
    terminal_event = asyncio.Event()
    output_parts: list[str] = []
    total_tokens = 0
    status = "completed"

    def on_text(event: LLMTextEmitted) -> None:
        output_parts.append(event.content)
        terminal_event.set()

    def on_pause(event: StreamPaused) -> None:
        nonlocal status
        status = "budget_exhausted" if event.reason == "budget_exhausted" else event.reason
        terminal_event.set()

    app_state.event_bus.subscribe(LLMTextEmitted, on_text)
    app_state.event_bus.subscribe(StreamPaused, on_pause)

    token_budget = max_tokens or app_state.config.runtime.max_tokens
    tasks = [
        asyncio.create_task(
            run_circuit_breaker(
                app_state.event_bus,
                app_state.session_id,
                max_retries=app_state.config.runtime.max_retries,
                max_tokens=token_budget,
            )
        ),
        asyncio.create_task(
            run_llm_worker(
                app_state.event_bus,
                app_state.session_id,
                app_state.database,
                app_state.config,
                app_state.skill_runner,
            )
        ),
        asyncio.create_task(
            run_skill_worker(
                app_state.event_bus,
                app_state.session_id,
                app_state.skill_runner,
            )
        ),
    ]

    try:
        await asyncio.sleep(0)
        await app_state.event_bus.publish_async(
            AgentInputAdded(session_id=app_state.session_id, user_content=objective)
        )
        await asyncio.wait_for(terminal_event.wait(), timeout=max_seconds)
    except TimeoutError:
        status = "budget_exhausted"
        output_parts.append(f"Time budget ({max_seconds}s) exhausted before the goal completed.")
    finally:
        await app_state.event_bus.publish_async(
            StreamPaused(
                session_id=app_state.session_id,
                reason="completed",
                threshold_breached=str(max_iterations),
            )
        )
        await asyncio.gather(*tasks, return_exceptions=True)

    recent_events = app_state.event_bus.get_recent_events(app_state.session_id)
    for event in recent_events:
        if isinstance(event, LLMActionEmitted):
            total_tokens += event.tokens_used

    return GoalRunResult(
        status=status,
        content="\n".join(output_parts).strip(),
        iterations=min(max_iterations, 1),
        total_tokens=total_tokens,
        events=[_event_log_entry(event) for event in recent_events],
    )


@app.command("events")
def events_log(
    session_id: Annotated[
        str | None,
        typer.Option(
            "--session-id",
            "-s",
            help="Only show events for this session id.",
        ),
    ] = None,
    event_types: Annotated[
        list[str] | None,
        typer.Option(
            "--type",
            "-e",
            help="Only show this event type. Repeat to include multiple types.",
        ),
    ] = None,
    since_id: Annotated[
        int | None,
        typer.Option(
            "--since-id",
            help="Replay events after this id. Omit to tail the latest rows.",
        ),
    ] = None,
    limit: Annotated[
        int,
        typer.Option(
            "--limit",
            "-n",
            help="Maximum rows to print per query.",
        ),
    ] = 50,
    follow: Annotated[  # noqa: FBT002
        bool,
        typer.Option(
            "--follow",
            "-f",
            help="Keep polling and print new events as processors emit them.",
        ),
    ] = False,
    poll_interval: Annotated[
        float,
        typer.Option(
            "--poll-interval",
            help="Seconds between polls when following.",
        ),
    ] = 0.5,
    json_output: Annotated[  # noqa: FBT002
        bool,
        typer.Option(
            "--json",
            help="Print newline-delimited JSON.",
        ),
    ] = False,
    include_payload: Annotated[  # noqa: FBT002
        bool,
        typer.Option(
            "--payload/--summary-only",
            help="Print the full decoded event payload under each event.",
        ),
    ] = True,
) -> None:
    """Observe processor events written to the durable event log."""
    try:
        config = HarnessConfig.load()
        from harness_poc.core.storage import create_db_engine  # noqa: PLC0415

        _print_events_log(
            EventLogOptions(
                engine=create_db_engine(config.runtime.database_url),
                session_id=session_id,
                event_types=event_types or [],
                since_id=since_id,
                limit=limit,
                follow=follow,
                poll_interval=poll_interval,
                json_output=json_output,
                include_payload=include_payload,
            )
        )
    except KeyboardInterrupt:
        raise typer.Exit from None
    except Exception as exc:
        logger.exception("Event log observer failed")
        print_error(str(exc))
        raise typer.Exit(1) from exc


def _print_events_log(options: EventLogOptions) -> None:
    last_seen_id = options.since_id
    printed_any = False
    while True:
        if last_seen_id is None:
            rows = fetch_latest_event_log_rows(
                options.engine,
                session_id=options.session_id,
                event_types=options.event_types,
                limit=options.limit,
            )
        else:
            rows = fetch_event_log_rows(
                options.engine,
                after_id=last_seen_id,
                session_id=options.session_id,
                event_types=options.event_types,
                limit=options.limit,
            )
        for row in rows:
            console.print(
                render_event_log_row(
                    row,
                    include_payload=options.include_payload,
                    json_output=options.json_output,
                ),
                markup=False,
            )
            last_seen_id = row.id
            printed_any = True

        if not options.follow:
            if not printed_any:
                console.print("[dim]No events matched.[/dim]")
            return

        time.sleep(options.poll_interval)


@dashboard_app.command("summary")
def dashboard_summary(
    json_output: Annotated[  # noqa: FBT002
        bool,
        typer.Option("--json", help="Print the dashboard snapshot as JSON."),
    ] = False,
) -> None:
    """Print a lightweight dashboard snapshot in the terminal."""
    try:
        config = HarnessConfig.load()
        from harness_poc.core.storage import create_db_engine  # noqa: PLC0415

        snapshot = fetch_dashboard_snapshot(create_db_engine(config.runtime.database_url))
    except Exception as exc:
        logger.exception("Dashboard summary failed")
        print_error(str(exc))
        raise typer.Exit(1) from exc

    if json_output:
        console.print(json.dumps(snapshot_to_dict(snapshot), indent=2), markup=False)
        return

    _print_dashboard_summary(snapshot)


@dashboard_app.command("serve")
def dashboard_serve(
    host: Annotated[str, typer.Option("--host", help="Host interface to bind.")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", "-p", help="Port to bind.")] = 8050,
    debug: Annotated[  # noqa: FBT002
        bool,
        typer.Option("--debug/--no-debug", help="Run Dash in debug mode."),
    ] = False,
) -> None:
    """Serve the read-only Dash dashboard."""
    try:
        config = HarnessConfig.load()
        from harness_poc.dashboard_app import create_dashboard_app  # noqa: PLC0415

        console.print(f"Dashboard: http://{host}:{port}")
        dash_app = create_dashboard_app(config.runtime.database_url)
        dash_app.run(host=host, port=port, debug=debug)
    except KeyboardInterrupt:
        raise typer.Exit from None
    except Exception as exc:
        logger.exception("Dashboard server failed")
        print_error(str(exc))
        raise typer.Exit(1) from exc


def _print_dashboard_summary(snapshot: DashboardSnapshot) -> None:
    data = snapshot_to_dict(snapshot)
    summary = data["summary"]
    table = Table(title="Harness Dashboard")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right")
    for key, label in [
        ("total_sessions", "Sessions"),
        ("total_events", "Events"),
        ("total_tokens", "Tokens"),
        ("skill_calls", "Skill Calls"),
        ("skill_failures", "Skill Failures"),
        ("context_pending", "Context Backlog"),
    ]:
        table.add_row(label, f"{int(summary.get(key, 0)):,}")
    console.print(table)

    if data["skills"]:
        skills = Table(title="Skill Performance")
        skills.add_column("Skill", style="cyan")
        skills.add_column("Calls", justify="right")
        skills.add_column("Failures", justify="right")
        skills.add_column("Last Status")
        for row in data["skills"]:
            skills.add_row(
                row["skill_name"],
                str(row["calls"]),
                str(row["failures"]),
                row["last_status"],
            )
        console.print(skills)

    if data["context_maps"]:
        maps = Table(title="Context Maps")
        maps.add_column("Corpus", style="cyan")
        maps.add_column("Version", justify="right")
        maps.add_column("Tokens", justify="right")
        maps.add_column("Pending", justify="right")
        for row in data["context_maps"]:
            maps.add_row(
                row["corpus_key"],
                str(row["version"]),
                str(row["token_count"]),
                str(row["pending_events"]),
            )
        console.print(maps)


def _event_log_entry(event: BaseEvent) -> dict[str, str]:
    tool = event.tool_name if isinstance(event, SkillCompleted) else ""
    status = event.status if isinstance(event, SkillCompleted) else ""
    return {"type": event.event_type, "tool": tool, "status": status}


def _append_state(command: str, text: str) -> None:
    app_state = _new_app_state()
    _run_command(lambda: append_session_state(app_state, command, text))
    console.print("[dim]This was added to a one-shot session. Use the REPL for multi-step propose/approve flows.[/dim]")


def _index_documents(
    app_state: AppState,
    paths: list[str],
    glob_pattern: str,
    *,
    exclude_dirs: list[str],
    force: bool,
) -> None:
    result = app_state.skill_runner.execute_skill(
        tool_name="index_documents",
        arguments={
            "paths": paths,
            "glob": glob_pattern,
            "exclude_dirs": exclude_dirs,
            "force": force,
        },
        session_id=app_state.session_id,
    )
    console.print(result.content, markup=False)
    if result.status != "success":
        raise typer.Exit(1)


def _new_app_state(
    session_id: str | None = None,
    *,
    corpus_key: str | None = None,
    mode: str = "chat",
) -> AppState:
    try:
        return build_app_state(session_id=session_id, corpus_key=corpus_key, mode=mode)
    except STARTUP_ERRORS as exc:
        logger.exception("Harness startup failed")
        print_error(f"Could not start harness: {exc}")
        raise typer.Exit(1) from exc


def _run_command(command: Callable[[], None]) -> None:
    try:
        command()
    except Exception as exc:
        logger.exception("CLI command failed")
        print_error(str(exc))
        raise typer.Exit(1) from exc


def _print_goal_cli_result(result: object) -> None:
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
    console.print(result.content)

    if result.events:
        console.print()
        console.print("[dim]--- Event Log ---[/dim]")
        for i, event in enumerate(result.events, 1):
            event_type = event.get("type", "?")
            tool = event.get("tool", "?")
            status = event.get("status", "")
            extra = f" ({status})" if status else ""
            console.print(f"[dim]{i}. [{event_type}] {tool}{extra}[/dim]")


@pipeline_app.command("list")
def pipeline_list() -> None:
    """List discovered pipeline YAML files."""
    app_state = _new_app_state()
    names = app_state.pipeline_runner.list_pipelines()
    if not names:
        console.print("[dim]No pipelines found.[/dim]")
        return
    for name in names:
        console.print(f"  {name}")


@pipeline_app.command("run")
def pipeline_run(
    name: Annotated[str, typer.Argument(help="Pipeline YAML name without .yaml.")],
    inputs: Annotated[
        list[str],
        typer.Option(
            "--input",
            "-i",
            help="Input as key=value. Repeat for multiple inputs.",
        ),
    ] = [],  # noqa: B006
) -> None:
    """Run a pipeline and print the node results."""
    parsed_inputs: dict[str, str] = {}
    for item in inputs:
        if "=" not in item:
            print_error(f"Invalid --input format '{item}': expected key=value")
            raise typer.Exit(1)
        key, _, value = item.partition("=")
        parsed_inputs[key.strip()] = value.strip()

    app_state = _new_app_state()
    try:
        result = app_state.pipeline_runner.run(name, parsed_inputs, app_state)
    except FileNotFoundError as exc:
        print_error(str(exc))
        raise typer.Exit(1) from exc
    except Exception as exc:
        print_error(f"Pipeline failed: {exc}")
        raise typer.Exit(1) from exc

    status_style = {"completed": "green", "failed": "red"}
    color = status_style.get(result.status, "white")
    console.print(f"\n[{color}]Pipeline '{name}': {result.status}[/{color}] ({result.duration_s:.1f}s)\n")

    for node_id, node_result in result.node_results.items():
        node_color = {
            "completed": "green",
            "failed": "red",
            "skipped": "yellow",
        }.get(node_result.status, "white")
        console.print(f"  [{node_color}]{node_id}: {node_result.status}[/{node_color}]")
        if node_result.output:
            console.print(node_result.output)

    if result.status == "failed":
        raise typer.Exit(1)


def _list_tools(app_state: AppState) -> None:
    """Print a table of built-in tools."""
    names = app_state.tool_runner.list_tool_names()
    if not names:
        console.print("[dim]No built-in tools found.[/dim]")
        return

    table = Table(title="Built-in Tools")
    table.add_column("Name", style="cyan")
    table.add_column("Description", style="dim")
    for name in names:
        # Re-discover to get descriptions
        for tool in app_state.tool_runner.discover_tools():
            fn = tool.get("function", {})
            if fn.get("name") == name:
                table.add_row(name, fn.get("description", ""))
                break
        else:
            table.add_row(name, "")
    console.print(table)


@cartographer_app.command("calibrate")
def cartographer_calibrate(
    corpus: Annotated[
        str | None,
        typer.Option(
            "--corpus",
            help="Corpus key to calibrate (default: <project_id>:codebase).",
        ),
    ] = None,
    window_days: Annotated[
        int,
        typer.Option(
            "--window-days",
            help="Lookback window in days for event counting.",
        ),
    ] = 14,
    min_events: Annotated[
        int,
        typer.Option(
            "--min-events",
            help="Minimum reference events before calibration runs.",
        ),
    ] = 50,
    apply_flag: Annotated[  # noqa: FBT002
        bool,
        typer.Option(
            "--apply/--dry-run",
            help="Write new weights to harness.yaml (default: --dry-run).",
        ),
    ] = False,
) -> None:
    """Calibrate priority_weights from observed reference and eviction rates.

    Reads MapEntryReferenced, MapEntryEvicted, and MapEntryInserted events
    from the event log and computes target priority_weights using a
    deterministic multiplicative formula.

    --dry-run prints a table showing current, target, and delta for each
    observation_type. --apply writes the new weights to harness.yaml.
    """
    from harness_poc.core.context_map.calibrate import run_calibration

    config = HarnessConfig.load()
    corpus_key = corpus or f"{config.project_id}:codebase"
    config_path = str(config.config_path) if apply_flag else None

    db = BlackboardDatabase.from_url(config.runtime.database_url)
    db.create_tables()

    result = run_calibration(
        db,
        corpus_key,
        window_days=window_days,
        min_events=min_events,
        dry_run=not apply_flag,
        config_path=config_path,
    )

    if result.status == "insufficient_data":
        console.print(f"[yellow]{result.message}[/yellow]")
        raise typer.Exit(0)

    # Print the table
    table = Table(title=f"Calibration — {corpus_key} ({window_days}d window)")
    table.add_column("Type", style="cyan")
    table.add_column("Current", justify="right")
    table.add_column("Target", justify="right")
    table.add_column("Δ", justify="right")

    for obs_type in sorted(result.weights):
        w = result.weights[obs_type]
        delta_str = f"{w['delta']:+.2f}"
        delta_style = "green" if w["delta"] > 0 else "red" if w["delta"] < 0 else "dim"
        table.add_row(
            obs_type,
            f"{w['current']:.2f}",
            f"{w['target']:.2f}",
            f"[{delta_style}]{delta_str}[/{delta_style}]",
        )

    console.print(table)
    console.print(
        f"\n[dim]References: {result.total_references}  "
        f"Evictions: {result.total_evictions}  "
        f"Insertions: {result.total_insertions}[/dim]"
    )

    if apply_flag and result.status == "success":
        console.print("\n[green]Weights written to harness.yaml.[/green]")
        console.print("[dim]A backup of the previous config was saved.[/dim]")


app.add_typer(workflow_app, name="workflow")
app.add_typer(state_app, name="state")
app.add_typer(skill_app, name="skill")
app.add_typer(tool_app, name="tool")
app.add_typer(documents_app, name="documents")
app.add_typer(pipeline_app, name="pipeline")
app.add_typer(dashboard_app, name="dashboard")
app.add_typer(acdl_app, name="acdl")
app.add_typer(cartographer_app, name="cartographer")
app.add_typer(v2_app, name="v2")


# ---------------------------------------------------------------------------
# V2 commands
# ---------------------------------------------------------------------------


@v2_app.command("probe")
def v2_probe(
    code: Annotated[str, typer.Argument(help="Python code to execute in the sandbox probe.")],
) -> None:
    """Run a fail-fast sandbox probe (Step #1).

    Executes code in an isolated sandbox. On failure, extracts constraints
    and warms the context map.
    """
    app_state = _new_app_state()
    _run_command(lambda: _run_v2_probe(app_state, code))


@v2_app.command("gate")
def v2_gate(
    workspace: Annotated[
        str | None,
        typer.Argument(help="Workspace path for the review gate. Defaults to project root."),
    ] = None,
) -> None:
    """Run the deterministic review gate (Step #3).

    Runs the test suite against the workspace. On success, updates the
    materialized context map to reflect verified state.
    """
    app_state = _new_app_state()
    _run_command(lambda: _run_v2_gate(app_state, workspace))


@v2_app.command("workflow")
def v2_workflow(
    spec_file: Annotated[
        str,
        typer.Argument(help="Path to a YAML spec file with probe, tasks, and workspace keys."),
    ],
    persona: Annotated[
        str,
        typer.Option("--persona", "-p", help="Persona to use (e.g. coder, reviewer)."),
    ] = "coder",
) -> None:
    """Run the full two-mode workflow (Steps #1-#3).

    The spec file is a YAML dict with optional keys:
      - probe: code string for sandbox exploration
      - tasks: list of {agent_type, objective} dicts for spec execution
      - workspace: path for the review gate
    """
    app_state = _new_app_state()
    _run_command(lambda: _run_v2_workflow(app_state, spec_file, persona))


@v2_app.command("context")
def v2_context(
    persona: Annotated[
        str,
        typer.Option("--persona", "-p", help="Persona to use (e.g. coder, code_reviewer)."),
    ] = "coder",
) -> None:
    """Materialize the context map through a persona+pedagogy lens.

    Loads the persona and pedagogy profile, materializes the context map,
    and prints the rendered prompt block that would be injected into the
    system message.
    """
    app_state = _new_app_state()
    _run_command(lambda: _run_v2_context(app_state, persona))


@v2_app.command("run")
def v2_run(
    objective: Annotated[
        str,
        typer.Argument(help="The goal/spec to execute."),
    ],
    mode: Annotated[
        str,
        typer.Option(
            "--mode", "-m",
            help="Execution mode: 'pipeline' (default) or 'react'.",
        ),
    ] = "pipeline",
    persona: Annotated[
        str,
        typer.Option("--persona", "-p", help="Persona to use (e.g. coder, reviewer)."),
    ] = "coder",
    spec_file: Annotated[
        str | None,
        typer.Option("--spec", "-s", help="Path to a YAML spec file (pipeline mode)."),
    ] = None,
    max_iterations: Annotated[
        int,
        typer.Option(
            "--max-iterations", "-n",
            help="Max loop iterations (react mode, default 50).",
        ),
    ] = 50,
    max_seconds: Annotated[
        float | None,
        typer.Option(
            "--max-seconds", "-t",
            help="Max wall-clock seconds (react mode).",
        ),
    ] = None,
    max_tokens: Annotated[
        int | None,
        typer.Option(
            "--max-tokens", "-k",
            help="Max cumulative tokens (react mode).",
        ),
    ] = None,
) -> None:
    """Run a v2 workflow or ReAct loop with mode selection.

    Examples:
        harness-poc v2 run --mode pipeline "implement a test"
        harness-poc v2 run --mode react "write a function"
    """
    app_state = _new_app_state(mode=mode)
    _run_command(
        lambda: _run_v2_mode(
            app_state,
            objective=objective,
            mode=mode,
            persona=persona,
            spec_file=spec_file,
            max_iterations=max_iterations,
            max_seconds=max_seconds,
            max_tokens=max_tokens,
        )
    )


# ---------------------------------------------------------------------------
# V2 internal runners
# ---------------------------------------------------------------------------
def _run_v2_probe(app_state: AppState, code: str) -> None:
    from harness_poc.v2.wiring import (
        build_context_engine,
        build_execution_engine,
        build_workflow_orchestrator,
    )

    ctx = build_context_engine(app_state.database, app_state.config)
    exec_eng = build_execution_engine(app_state.database, app_state.config)
    orch = build_workflow_orchestrator(ctx, exec_eng)

    result = orch.run_exploration_probe(code=code, session_id=app_state.session_id)

    if result.success:
        print_text(f"Probe passed: exit={result.exit_code}")
        print_text(f"stdout:\n{result.stdout}")
    else:
        print_error(f"Probe failed: exit={result.exit_code}")
        print_error(f"stderr:\n{result.stderr}")
        if result.discovered_constraints:
            print_text("\nDiscovered constraints:")
            for c in result.discovered_constraints:
                print_text(f"  [{c['type']}] {c['detail']}")


def _run_v2_gate(app_state: AppState, workspace: str | None) -> None:
    from harness_poc.v2.wiring import build_execution_engine

    exec_eng = build_execution_engine(app_state.database, app_state.config)
    ws = workspace or str(app_state.config.project_root)

    try:
        passed = exec_eng.execute_deterministic_gate(
            workspace_path=ws,
            session_id=app_state.session_id,
        )
    except Exception as exc:
        print_error(f"Gate error: {exc}")
        return

    if passed:
        print_text("Gate PASSED — context map reflects verified state.")
    else:
        print_error("Gate FAILED — test suite did not pass cleanly.")


def _run_v2_workflow(app_state: AppState, spec_file: str, persona: str) -> None:
    from pathlib import Path

    import yaml

    from harness_poc.v2.wiring import (
        build_context_engine,
        build_execution_engine,
        build_workflow_orchestrator,
    )

    spec_path = Path(spec_file)
    if not spec_path.exists():
        print_error(f"Spec file not found: {spec_file}")
        return

    spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    if not isinstance(spec, dict):
        print_error("Spec file must be a YAML mapping")
        return

    ctx = build_context_engine(app_state.database, app_state.config)
    exec_eng = build_execution_engine(app_state.database, app_state.config)
    orch = build_workflow_orchestrator(ctx, exec_eng)

    result = orch.execute_workflow(
        spec=spec,
        persona_id=persona,
        probe_code=spec.get("probe"),
        workspace_path=spec.get("workspace"),
    )

    print_text(f"Workflow {result.workflow_id}")
    print_text(f"  Steps completed: {result.steps_completed}")

    if result.probe:
        status = "PASS" if result.probe.success else "FAIL"
        print_text(f"  Probe: {status} (exit={result.probe.exit_code})")
        if result.probe.discovered_constraints:
            print_text(f"    Constraints: {len(result.probe.discovered_constraints)}")

    if result.execution:
        status = "PASS" if result.execution.all_passed else "FAIL"
        print_text(
            f"  Execution: {status} "
            f"({len(result.execution.sub_agents)} agents, "
            f"{result.execution.failure_count} failures)"
        )

    if result.gate:
        status = "PASS" if result.gate.passed else "FAIL"
        print_text(f"  Gate: {status} ({result.gate.test_count} tests)")

    print_text(f"  Context refreshed: {result.context_map_refreshed}")


def _run_v2_context(app_state: AppState, persona: str) -> None:
    from harness_poc.v2.wiring import build_v2_system_prompt_block

    block = build_v2_system_prompt_block(
        app_state.database,
        app_state.config,
        persona_id=persona,
        working_context={"session_id": app_state.session_id},
    )

    if block:
        print_text(block)
    else:
        print_error(f"Could not materialize context for persona '{persona}'.")


def _run_v2_mode(
    app_state: AppState,
    *,
    objective: str,
    mode: str,
    persona: str,
    spec_file: str | None,
    max_iterations: int,
    max_seconds: float | None,
    max_tokens: int | None,
) -> None:
    """Run v2 in the selected mode (pipeline or react).

    Uses app_state.v2_runtime if already built (e.g. from build_app_state),
    otherwise constructs one on the fly.
    """
    runtime = app_state.v2_runtime
    if runtime is None:
        from harness_poc.v2.wiring import build_v2_runtime  # noqa: PLC0415

        runtime = build_v2_runtime(app_state.identity, app_state.config, mode=mode)

    if mode == "pipeline":
        _run_v2_pipeline_mode(
            runtime,
            objective=objective,
            persona=persona,
            spec_file=spec_file,
            session_id=app_state.session_id,
        )
    elif mode == "react":
        asyncio.run(
            _run_v2_react_mode(
                runtime,
                app_state=app_state,
                objective=objective,
                max_iterations=max_iterations,
                max_seconds=max_seconds,
                max_tokens=max_tokens,
            )
        )
    else:
        print_error(f"Unknown mode: {mode}")


def _run_v2_pipeline_mode(
    runtime: V2Runtime,
    *,
    objective: str,
    persona: str,
    spec_file: str | None,
    session_id: str,
) -> None:
    """Run the v2 pipeline mode with progress output."""
    from pathlib import Path

    import yaml

    from harness_poc.core.events import (
        ExecutionCompleted,
        GateCompleted,
        ProbeCompleted,
    )

    orch = runtime.orchestrator
    if orch is None:
        print_error("Pipeline orchestrator not available")
        return
    bus = runtime.bus

    if spec_file:
        spec_path = Path(spec_file)
        if not spec_path.exists():
            print_error(f"Spec file not found: {spec_file}")
            return
        spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
        if not isinstance(spec, dict):
            print_error("Spec file must be a YAML mapping")
            return
    else:
        spec = {"goal": objective, "tasks": []}

    probe_code = cast("str | None", spec.get("probe"))
    workspace_path = cast("str | None", spec.get("workspace"))

    # Subscribe progress handlers so the user sees step-by-step output.
    # The pipeline runs synchronously within bus.publish(), so these
    # fire inline as each step completes. The gate handler prints the
    # final summary since it's always the last step to fire.

    def on_probe(event: ProbeCompleted) -> None:
        success = event.success
        constraints = event.constraints
        if probe_code is None:
            print_text("  Probe: skipped (no probe code)")
        elif success:
            print_text("  Probe: PASSED")
        else:
            print_text(
                f"  Probe: FAILED — {len(constraints)} constraint(s) discovered"
            )

    def on_execution(event: ExecutionCompleted) -> None:
        agents = event.sub_agents
        all_passed = event.all_passed
        if not agents:
            print_text("  Execution: skipped (no tasks)")
        elif all_passed:
            print_text(f"  Execution: PASSED — {len(agents)} agent(s)")
        else:
            failed = sum(
                1 for a in agents if a.get("output_label") != "completed"
            )
            print_text(f"  Execution: FAILED — {failed}/{len(agents)} agent(s)")

    def on_gate(event: GateCompleted) -> None:
        passed = event.passed
        test_count = event.test_count
        if workspace_path is None:
            print_text("  Gate: skipped (no workspace)")
        elif passed:
            print_text(f"  Gate: PASSED — {test_count} test(s)")
        else:
            print_text(f"  Gate: FAILED — {test_count} test(s)")
        # Gate is always the last step — print completion marker here
        print_text("  Done.")

    bus.subscribe(ProbeCompleted, on_probe)
    bus.subscribe(ExecutionCompleted, on_execution)
    bus.subscribe(GateCompleted, on_gate)

    print_text(f"Pipeline: {objective}")

    # Start the event-driven pipeline (runs synchronously)
    orch.run_pipeline_via_bus(
        spec=spec,
        persona_id=persona,
        probe_code=probe_code,
        workspace_path=workspace_path,
        session_id=session_id,
    )


async def _run_v2_react_mode(
    runtime: V2Runtime,
    *,
    app_state: AppState,
    objective: str,
    max_iterations: int,
    max_seconds: float | None,
    max_tokens: int | None,
) -> None:
    """Run the v2 ReAct mode using the v2 subscribers."""
    bus = runtime.bus
    session_id = app_state.session_id

    if runtime.circuit_breaker is None:
        print_error("CircuitBreaker not available")
        return
    if runtime.llm_worker is None:
        print_error("LlmWorker not available")
        return
    if runtime.tool_worker is None:
        print_error("ToolWorker not available")
        return
    if runtime.goal_evaluator is None:
        print_error("GoalEvaluator not available")
        return

    terminal_event = asyncio.Event()
    output_parts: list[str] = []
    iteration = 0

    # Progress output — surface what the agent is doing
    def on_text(event: LLMTextEmitted) -> None:
        output_parts.append(event.content)
        terminal_event.set()

    def on_pause(event: StreamPaused) -> None:
        terminal_event.set()

    def on_goal(event: GoalEvaluated) -> None:
        terminal_event.set()

    # Progress output — surface what the agent is doing
    def on_llm_action(event: LLMActionEmitted) -> None:
        nonlocal iteration
        iteration += 1
        tokens = event.tokens_used
        print_text(f"  [{iteration}] LLM response ({tokens} tokens)")

    def on_tool_request(event: SkillRequested) -> None:
        skill = event.skill_name
        print_text(f"  [{iteration}] \u2192 calling {skill}()")

    def on_tool_complete(event: SkillCompleted) -> None:
        status = event.status
        tool = event.skill_name or event.tool_name or "unknown"
        marker = "\u2713" if status == "success" else "\u2717"
        print_text(f"  [{iteration}] \u2190 {tool}() {marker} ({status})")

    bus.subscribe(LLMTextEmitted, on_text)
    bus.subscribe(StreamPaused, on_pause)
    bus.subscribe(GoalEvaluated, on_goal)
    bus.subscribe(LLMActionEmitted, on_llm_action)
    bus.subscribe(SkillRequested, on_tool_request)
    bus.subscribe(SkillCompleted, on_tool_complete)

    tasks = [
        asyncio.create_task(
            runtime.circuit_breaker.run(bus, session_id)
        ),
        asyncio.create_task(
            runtime.llm_worker.run(bus, session_id)
        ),
        asyncio.create_task(
            runtime.tool_worker.run(bus, session_id)
        ),
        asyncio.create_task(
            runtime.goal_evaluator.run(bus, session_id)
        ),
    ]

    try:
        await asyncio.sleep(0)
        bus.publish(
            AgentInputAdded(
                session_id=session_id,
                user_content=objective,
            )
        )
        await asyncio.wait_for(terminal_event.wait(), timeout=max_seconds)
    except TimeoutError:
        output_parts.append(
            f"Time budget ({max_seconds}s) exhausted before the goal completed."
        )
    finally:
        bus.publish(
            StreamPaused(
                session_id=session_id,
                reason="completed",
                threshold_breached=str(max_iterations),
            )
        )
        await asyncio.gather(*tasks, return_exceptions=True)

    output = "\n".join(output_parts).strip()
    if output:
        print_text(output)
    else:
        print_text("ReAct loop completed (no text output).")
