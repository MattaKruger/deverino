from __future__ import annotations

from typing import TYPE_CHECKING

from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from harness_poc.core.skills import SkillRunner
    from harness_poc.core.workflow_runner import WorkflowRunResult


console = Console()

_tui_on_markdown: Callable[[str], None] | None = None
_tui_on_error: Callable[[str], None] | None = None
_tui_on_text: Callable[[str, bool], None] | None = None


def set_tui_handlers(
    *,
    on_markdown: Callable[[str], None],
    on_error: Callable[[str], None],
    on_text: Callable[[str, bool], None],
) -> None:
    global _tui_on_markdown, _tui_on_error, _tui_on_text  # noqa: PLW0603
    _tui_on_markdown = on_markdown
    _tui_on_error = on_error
    _tui_on_text = on_text


def clear_tui_handlers() -> None:
    global _tui_on_markdown, _tui_on_error, _tui_on_text  # noqa: PLW0603
    _tui_on_markdown = None
    _tui_on_error = None
    _tui_on_text = None


def print_markdown(markdown: str) -> None:
    if _tui_on_markdown is not None:
        _tui_on_markdown(markdown)
    else:
        console.print(Markdown(markdown))


def print_error(message: str) -> None:
    if _tui_on_error is not None:
        _tui_on_error(message)
    else:
        console.print(f"[red]{message}[/red]")


def print_text(text: str, *, markup: bool = True) -> None:
    if _tui_on_text is not None:
        _tui_on_text(text, markup)
    else:
        console.print(text, markup=markup)


def print_skill_table(skill_files: list[Path], skill_runner: SkillRunner) -> None:
    if not skill_files:
        print_text("No skills found.")
        return

    table = Table(title="Skills")
    table.add_column("Name", style="cyan", no_wrap=True)
    table.add_column("Source", style="dim", no_wrap=True)
    table.add_column("Description")

    for skill_file in skill_files:
        skill = skill_runner.parse_skill_document(skill_file)
        metadata = skill["metadata"]
        source = (
            "system"
            if skill_file.is_relative_to(skill_runner.config.paths.system_skills)
            else "project"
        )
        table.add_row(metadata["name"], source, metadata["description"])

    console.print(table)


def print_workflow_result(result: WorkflowRunResult) -> None:
    print_text(
        f"Workflow [cyan]{result.workflow_name}[/cyan] completed with status: "
        f"[green]{result.status}[/green]"
    )
    if result.outputs:
        table = Table(title="Workflow States")
        table.add_column("State", style="cyan", no_wrap=True)
        table.add_column("Skill", no_wrap=True)
        table.add_column("Status", no_wrap=True)
        for output in result.outputs:
            table.add_row(output.state_name, output.skill_name, output.result.status)
        console.print(table)
    print_text(result.final_content)
