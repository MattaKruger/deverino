"""CLI commands for ACDL file operations."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from harness_poc.console import console

acdl_app = typer.Typer(
    name="acdl",
    help="Validate and inspect ACDL specification files.",
    rich_markup_mode="rich",
    no_args_is_help=True,
)


@acdl_app.command(name="validate")
def validate_acdl(
    files: Annotated[
        list[Path],
        typer.Argument(
            help="One or more .acdl files to validate.",
            exists=True,
            file_okay=True,
            dir_okay=False,
        ),
    ],
) -> None:
    """Validate one or more .acdl files, reporting any syntax errors."""
    from harness_poc.core.acdl import ParseError, parse

    failed = 0
    for path in files:
        source = path.read_text()
        try:
            ast = parse(source, filename=str(path))
            console.print(f"[green]✓[/green] {path} — {len(ast.blocks)} blocks")
        except ParseError as e:
            console.print(f"[red]✗[/red] {path}")
            console.print(f"  {e}", markup=False)
            failed += 1

    if failed:
        raise typer.Exit(code=1)
