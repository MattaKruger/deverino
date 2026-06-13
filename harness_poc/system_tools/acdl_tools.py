"""acdl_inspect — inspect an ACDL specification file.

Returns a structural summary (fragments, prompts, namespaces) as JSON.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from harness_poc.core.acdl import parse, to_dict
from harness_poc.core.skills import SkillResult

if TYPE_CHECKING:
    from harness_poc.core.tools import ToolContext


def acdl_inspect(
    ctx: ToolContext,  # noqa: ARG001
    file_path: str = "",
) -> SkillResult:
    """Parse an .acdl file and return its structural summary."""
    path = Path(file_path)
    if not path.exists():
        return SkillResult(
            status="failed",
            content=f"File not found: {file_path}",
        )
    if path.suffix != ".acdl":
        return SkillResult(
            status="failed",
            content=f"Not an .acdl file: {file_path}",
        )

    try:
        source = path.read_text()
        ast = parse(source, filename=str(path))
        summary = {
            "file": str(path),
            "block_count": len(ast.blocks),
            "str_frags": [f.name for f in ast.str_frags()],
            "role_frags": [f.name for f in ast.role_frags()],
            "prompts": [p.name for p in ast.prompts()],
            "namespaces": [ns.name for ns in ast.namespaces()],
        }
        return SkillResult(
            status="success",
            content=json.dumps(summary, indent=2),
            artifacts={"acdl_summary": summary, "acdl_ast": to_dict(ast)},
        )
    except Exception as e:
        return SkillResult(
            status="failed",
            content=f"Failed to parse {file_path}: {e}",
        )


# ── Register ──────────────────────────────────────────────────────────

from harness_poc.system_tools import register as _register  # noqa: E402

_register(
    name="acdl_inspect",
    description=(
        "Parse an .acdl (Agent Context Definition Language) specification file "
        "and return its structural summary: fragment definitions, prompt "
        "definitions, and namespace blocks. Use this to inspect the harness's "
        "own architecture specification."
    ),
    parameters={
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Path to the .acdl file to inspect (e.g., 'deverino_react.acdl').",
            },
        },
        "required": ["file_path"],
    },
    handler=acdl_inspect,
)
