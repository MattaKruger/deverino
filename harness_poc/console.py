from __future__ import annotations

from typing import TYPE_CHECKING

from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table

if TYPE_CHECKING:
    from pathlib import Path

    from harness_poc.core.skill_runner import SkillRunner
    from harness_poc.core.workflow_runner import WorkflowRunResult


console = Console()


def print_markdown(markdown: str) -> None:
    console.print(Markdown(markdown))


def print_error(message: str) -> None:
    console.print(f"[red]{message}[/red]")


def print_skill_table(skill_files: list[Path], skill_runner: SkillRunner) -> None:
    if not skill_files:
        console.print("No skills found.")
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
        table.add_row(
            metadata["name"],
            source,
            metadata["description"],
        )

    console.print(table)


def print_workflow_result(result: WorkflowRunResult) -> None:
    console.print(
        f"Workflow [cyan]{result.workflow_name}[/cyan] completed with status: "
        f"[green]{result.status}[/green]"
    )
    if result.outputs:
        table = Table(title="Workflow States")
        table.add_column("State", style="cyan", no_wrap=True)
        table.add_column("Skill", no_wrap=True)
        table.add_column("Status", no_wrap=True)
        for output in result.outputs:
            table.add_row(
                output.state_name,
                output.skill_name,
                output.result.status,
            )
        console.print(table)
    console.print(result.final_content)
