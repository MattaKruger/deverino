"""CLI commands for ACDL file operations."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from rich.markup import escape as _rich_escape

from harness_poc.console import console


def _index_to_str(idx: object) -> str:
    """Render an index expression as a readable string."""
    from harness_poc.core.acdl.ast import ContextVar, TemplateCall, TimeIndex

    if isinstance(idx, TimeIndex):
        inner = _index_to_str(idx.value)
        return f"@{inner}"
    if isinstance(idx, TemplateCall):
        if idx.arguments:
            args = ", ".join(_index_to_str(a) for a in idx.arguments)
            return f"{idx.name}({args})"
        return idx.name
    if isinstance(idx, ContextVar):
        path = ".".join(idx.path)
        if idx.namespace == "$":
            return f"${path}"
        return f"{idx.namespace}.{path}"
    return str(idx)


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


@acdl_app.command(name="inspect")
def inspect_acdl(
    file: Annotated[
        Path,
        typer.Argument(
            help="An .acdl file to inspect.",
            exists=True,
            file_okay=True,
            dir_okay=False,
        ),
    ],
    fragments_only: Annotated[
        bool,
        typer.Option("--fragments", "-f", help="Show only fragment definitions."),
    ] = False,
    prompts_only: Annotated[
        bool,
        typer.Option("--prompts", "-p", help="Show only prompt definitions."),
    ] = False,
    namespaces_only: Annotated[
        bool,
        typer.Option("--namespaces", "-n", help="Show only namespace blocks."),
    ] = False,
) -> None:
    """Inspect an .acdl file: list fragments, prompts, and namespaces."""
    from harness_poc.core.acdl import parse
    from harness_poc.core.acdl.ast import (
        NamespaceDef,
        PromptDef,
        RoleFragDef,
        StrFragDef,
    )

    source = file.read_text()
    ast = parse(source, filename=str(file))

    str_frags = [b for b in ast.blocks if isinstance(b, StrFragDef)]
    role_frags = [b for b in ast.blocks if isinstance(b, RoleFragDef)]
    prompts = [b for b in ast.blocks if isinstance(b, PromptDef)]
    namespaces = [b for b in ast.blocks if isinstance(b, NamespaceDef)]

    show_all = not (fragments_only or prompts_only or namespaces_only)

    if show_all:
        console.print(f"\n[bold]{file}[/bold] — {len(ast.blocks)} blocks")
        console.print(
            f"  {len(str_frags)} StrFrags, {len(role_frags)} RoleFrags, "
            f"{len(prompts)} prompts, {len(namespaces)} namespaces"
        )

    if show_all or fragments_only:
        if str_frags:
            console.print("\n[bold]StrFrag definitions:[/bold]")
            for f in str_frags:
                params_str = f"[{', '.join(f.params)}]" if f.params else ""
                params_str = _rich_escape(params_str)
                console.print(f"  {f.name}{params_str}  ([italic]{len(f.body)} items[/italic])")
        if role_frags:
            console.print("\n[bold]RoleFrag definitions:[/bold]")
            for f in role_frags:
                params_str = f"[{', '.join(f.params)}]" if f.params else ""
                params_str = _rich_escape(params_str)
                console.print(f"  {f.name}{params_str}  ([italic]{len(f.body)} items[/italic])")

    if show_all or prompts_only:
        if prompts:
            console.print("\n[bold]Prompt definitions:[/bold]")
            for p in prompts:
                idx_parts: list[str] = []
                for i in p.indices:
                    idx_parts.append(_index_to_str(i))
                idx_str = f"[{', '.join(idx_parts)}]" if idx_parts else ""
                idx_str = _rich_escape(idx_str)
                console.print(f"  {p.name}{idx_str}  ([italic]{len(p.body)} items[/italic])")

    if show_all or namespaces_only:
        if namespaces:
            console.print("\n[bold]Namespace blocks:[/bold]")
            for ns in namespaces:
                console.print(f"  {ns.name}  ([italic]{len(ns.bindings)} bindings[/italic])")
