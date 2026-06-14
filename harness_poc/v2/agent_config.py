"""Agent configuration loader for sub-agents.

Reads ``subagents/<name>.yml`` and resolves tool references to callables
that can be passed directly to ``pydantic_ai.Agent(tools=...)``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any
import yaml


if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AgentConfig:
    """Resolved configuration for a sub-agent persona."""

    persona: str
    """Persona name (matches a file in ``personas/``)."""

    tools: list[Callable[..., object]] = field(default_factory=list)
    """Resolved tool callables ready for ``Agent(tools=...)``."""

    permissions: dict[str, str] = field(default_factory=dict)
    """Documented permissions (not enforced at runtime yet)."""

    @classmethod
    def from_name(cls, agents_dir: Path, name: str, *, tool_registry: dict[str, Any]) -> AgentConfig:
        """Load and resolve an agent configuration by name.

        Args:
            agents_dir: Path to the ``subagents/`` directory.
            name: Agent identifier (matches ``<name>.yml``).
            tool_registry: The global tool registry from
                ``harness_poc.system_tools.get_registry()``.

        Returns:
            A fully resolved ``AgentConfig``.

        Raises:
            FileNotFoundError: If ``subagents/<name>.yml`` does not exist.
        """
        config_path = agents_dir / f"{name}.yml"
        if not config_path.exists():
            raise FileNotFoundError(f"Agent config not found: {config_path}")

        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            msg = f"Agent config {config_path} must be a YAML mapping"
            raise ValueError(msg)

        persona = raw.get("persona", name)
        tool_names: list[str] = raw.get("tools", [])
        permissions: dict[str, str] = raw.get("permissions", {})

        resolved: list[Callable[..., object]] = []
        for tool_name in tool_names:
            tool_fn = _resolve_tool(tool_name, tool_registry)
            if tool_fn is not None:
                resolved.append(tool_fn)
            else:
                logger.warning(
                    "Agent '%s': tool '%s' not found in registry — skipping",
                    name,
                    tool_name,
                )

        return cls(persona=persona, tools=resolved, permissions=permissions)


# ---------------------------------------------------------------------------
# Tool resolution
# ---------------------------------------------------------------------------


def _resolve_tool(
    name: str,
    tool_registry: dict[str, Any],
) -> Callable[..., object] | None:
    """Resolve a tool name to a callable.

    Checks the built-in tool registry first, then falls back to special
    skill-backed tools like ``semble_search``.
    """
    # 1. Built-in tool from system_tools/ registry
    entry = tool_registry.get(name)
    if entry is not None:
        handler = entry.get("handler")
        if callable(handler):
            return handler
        logger.warning("Tool '%s' registered but handler is not callable", name)
        return None

    # 2. Skill-backed tools (loaded via skill runner)
    if name == "semble_search":
        return _make_semble_search()

    return None


def _make_semble_search() -> Callable[..., object]:
    """Create a ``semble_search`` callable that invokes the skill runner."""

    def semble_search(query: str, path: str = ".", top_k: int = 10) -> dict[str, Any]:
        """Semantic code search. Returns file paths, line numbers, and snippets."""
        # Import lazily to avoid circular imports
        from harness_poc.core.skills.skill_runner import SkillRunner

        # We need access to the skill runner. In the sub-agent context,
        # we don't have a SkillRunner instance available. We use a
        # module-level reference that gets set by the harness at startup.
        runner = _get_skill_runner()
        if runner is None:
            return {
                "error": "semble_search not available — no skill runner configured for sub-agents",
            }

        try:
            result = runner.execute_skill(
                skill_name="semble_search",
                arguments={"args": {"query": query, "path": path, "top_k": top_k}},
                session_id="_subagent_",
            )
            return {"status": result.status, "content": result.content}
        except Exception as exc:
            return {"error": f"semble_search failed: {exc}"}

    # Preserve metadata for pydantic_ai tool schema generation
    semble_search.__name__ = "semble_search"
    semble_search.__doc__ = (
        "Semantic code search. Finds code by describing what it does. "
        "Args: query (what to search for), path (directory, default '.'), "
        "top_k (max results, default 10)."
    )
    return semble_search


# ---------------------------------------------------------------------------
# Skill runner access (set by harness at startup)
# ---------------------------------------------------------------------------

_skill_runner: Any = None


def set_skill_runner(runner: Any) -> None:
    """Store a reference to the global SkillRunner for sub-agent tool use."""
    global _skill_runner
    _skill_runner = runner


def _get_skill_runner() -> Any:
    return _skill_runner
