from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Annotated

import typer

from harness_poc.app_factory import STARTUP_ERRORS, AppState, build_app_state
from harness_poc.console import console, print_error
from harness_poc.core.goal_runner import GoalRunner, GoalRunResult
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

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from collections.abc import Callable


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
pipeline_app = typer.Typer(
    help="Run declarative DAG pipeline YAML files.",
    rich_markup_mode="rich",
)


@app.callback(invoke_without_command=True)
def main_callback(ctx: typer.Context) -> None:
    """Interactive LLM harness proof of concept."""
    if ctx.invoked_subcommand is not None:
        return
    app_state = _new_app_state()
    run_repl(app_state)
    raise typer.Exit


@app.command()
def repl() -> None:
    """Start the interactive REPL."""
    app_state = _new_app_state()
    run_repl(app_state)


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
    """Run an autonomous ReAct goal execution loop."""
    app_state = _new_app_state()
    runner = GoalRunner(
        max_iterations=max_iterations,
        max_seconds=max_seconds,
        max_tokens=max_tokens,
    )
    try:
        result = runner.run(goal=objective, app_state=app_state)
    except Exception as exc:
        logger.exception(
            "CLI goal command failed",
            extra={"session_id": app_state.session_id, "objective": objective},
        )
        print_error(f"Goal loop failed: {exc}")
        raise typer.Exit(1) from exc

    _print_goal_cli_result(result)


def _append_state(command: str, text: str) -> None:
    app_state = _new_app_state()
    _run_command(lambda: append_session_state(app_state, command, text))
    console.print(
        "[dim]This was added to a one-shot session. Use the REPL for "
        "multi-step propose/approve flows.[/dim]"
    )


def _new_app_state() -> AppState:
    try:
        return build_app_state()
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
        typer.Option("--input", "-i", help="Input as key=value. Repeat for multiple inputs."),
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
    console.print(
        f"\n[{color}]Pipeline '{name}': {result.status}[/{color}] ({result.duration_s:.1f}s)\n"
    )

    for node_id, node_result in result.node_results.items():
        node_color = {"completed": "green", "failed": "red", "skipped": "yellow"}.get(
            node_result.status, "white"
        )
        console.print(f"  [{node_color}]{node_id}: {node_result.status}[/{node_color}]")
        if node_result.output:
            console.print(node_result.output)

    if result.status == "failed":
        raise typer.Exit(1)


app.add_typer(workflow_app, name="workflow")
app.add_typer(state_app, name="state")
app.add_typer(skill_app, name="skill")
app.add_typer(pipeline_app, name="pipeline")
