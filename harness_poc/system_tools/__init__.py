"""Built-in tool registry for the Deverino harness.

Tools registered here are LLM-callable primitives — pure functions that execute
directly without spawning sub-agents or making their own LLM calls.  They
correspond to Hermes's ``tools/`` layer, distinct from skills (procedural
knowledge documents) and agent-skills (orchestration that spawns sub-agents).

Usage in a tool module (e.g. file_tools.py)::

    from harness_poc.system_tools import register as _register

    def read_file(path: str, offset: int = 1, limit: int = 500) -> dict:
        ...

    _register(
        name="read_file",
        description="Read a text file with line numbers...",
        parameters={"type": "object", "properties": {...}, "required": ["path"]},
        handler=read_file,
    )
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

_registry: dict[str, dict[str, Any]] = {}


def register(
    name: str,
    description: str,
    parameters: dict[str, Any],
    handler: Callable[..., object],
    **extra: Any,  # noqa: ANN401
) -> None:
    """Register a built-in tool.

    Args:
        name: Tool name exposed to the LLM (e.g. ``"read_file"``).
        description: Tool description in the JSON function schema.
        parameters: JSON Schema ``parameters`` object.
        handler: Callable that receives keyword arguments and returns a dict.
        **extra: Internal flags (e.g. ``_skill_backed=True``).

    """
    _registry[name] = {
        "name": name,
        "description": description,
        "parameters": parameters,
        "handler": handler,
        **extra,
    }


def get_registry() -> dict[str, dict[str, Any]]:
    """Return a shallow copy of the current tool registry."""
    return dict(_registry)
