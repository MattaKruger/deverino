"""ToolRunner -- discovers and executes built-in (LLM-callable) tools.

Mirrors ``SkillRunner`` in shape but is simpler for built-in tools: those
have no SKILL.md, no permissions, no YAML frontmatter. They register
themselves at import time via ``harness_poc.system_tools.register()``.

Built-in tools are pure functions -- no sub-agent spawning, no LLM
involvement. They correspond to Hermes's ``tools/`` layer.

During the migration period (Phase 2), ToolRunner also scans
``system_skills/`` for SKILL.md files with ``type: tool`` in the YAML
frontmatter. These tool-level skills are registered as skill-backed
handlers that delegate execution to ``SkillRunner``. When the migration
completes (Phase 4), the tool code itself will move into
``system_tools/``.
"""

from __future__ import annotations

import importlib.util
import json as _json
import logging
from typing import TYPE_CHECKING, Any

from harness_poc.core.tool_result import ToolResult

if TYPE_CHECKING:
    from pathlib import Path

    from harness_poc.core.config import HarnessConfig
    from harness_poc.core.skill_runner import SkillRunner

logger = logging.getLogger(__name__)


class ToolRunner:
    """Discover and execute built-in tools from ``system_tools/`` and
    tool-level skills from ``system_skills/``.

    During the migration period (Phase 2), ToolRunner also scans
    ``system_skills/`` and ``project_skills/`` for SKILL.md files
    with ``type: tool`` in the YAML frontmatter.
    """

    def __init__(
        self,
        config: HarnessConfig,
        *,
        skill_runner: SkillRunner | None = None,
    ) -> None:
        self._tools_dir: Path = config.paths.system_tools
        self._skills_dirs: tuple[Path, Path] = (
            config.paths.system_skills,
            config.paths.project_skills,
        )
        self._skill_runner: SkillRunner | None = skill_runner
        self._discovered = False

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def _ensure_discovered(self) -> None:
        """Import tool modules + scan system_skills/ for type:tool skills."""
        if self._discovered:
            return

        # 1. Built-in tools from system_tools/ (Python modules with register())
        if self._tools_dir.exists():
            for py_file in sorted(self._tools_dir.glob("*.py")):
                if py_file.name.startswith("_"):
                    continue
                module_name = f"harness_poc.system_tools.{py_file.stem}"
                try:
                    spec = importlib.util.spec_from_file_location(
                        module_name, py_file
                    )
                    if spec is None or spec.loader is None:
                        logger.warning("Could not load tool module: %s", py_file)
                        continue
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                except Exception:
                    logger.exception("Failed to load tool module: %s", py_file)

        # 2. Tool-level skills from system_skills/ + project_skills/ (SKILL.md with type: tool)
        for skills_dir in self._skills_dirs:
            _discover_tool_skills(skills_dir, self._skill_runner)

        self._discovered = True

    def discover_tools(self) -> list[dict[str, Any]]:
        """Return tools in the same shape as ``SkillRunner.discover_skills()``.

        Each entry::

            {
                "type": "function",
                "function": {
                    "name": str,
                    "description": str,
                    "parameters": dict,  # JSON Schema
                    "auto_invokable": True,
                },
            }
        """
        from harness_poc.system_tools import get_registry  # noqa: PLC0415

        self._ensure_discovered()
        tools: list[dict[str, Any]] = []
        for name, info in get_registry().items():
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": info["description"],
                        "parameters": info["parameters"],
                        "auto_invokable": True,
                    },
                }
            )
        return tools

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def execute_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        session_id: str = "",
    ) -> str:
        """Execute a tool and return its JSON-serialized result.

        For skill-backed tools (discovered from system_skills/), the
        ``session_id`` is forwarded to ``SkillRunner.execute_skill()``.
        Built-in tools ignore ``session_id``.

        Returns a JSON string so it plugs directly into the PydanticAI
        tool pipeline (same contract as ``execute_skill_as_tool``).
        """
        from harness_poc.system_tools import get_registry  # noqa: PLC0415

        self._ensure_discovered()
        info = get_registry().get(tool_name)
        if info is None:
            return _json.dumps({"error": f"Unknown tool: {tool_name}"})

        handler = info["handler"]
        try:
            # Skill-backed tools need session_id injected
            if info.get("_skill_backed") and self._skill_runner is not None:
                result = self._skill_runner.execute_skill(
                    tool_name=tool_name,
                    arguments=arguments,
                    session_id=session_id,
                )
                return _json.dumps(result.to_dict(), ensure_ascii=False)

            result = handler(**arguments)
        except TypeError as e:
            return _json.dumps({"error": f"Invalid arguments for {tool_name}: {e}"})
        except Exception:
            logger.exception("Tool execution failed: %s", tool_name)
            return _json.dumps(
                {"error": f"Tool {tool_name} raised an unexpected error."}
            )

        if isinstance(result, ToolResult):
            return _json.dumps(result.to_dict(), ensure_ascii=False)

        return _json.dumps(result, ensure_ascii=False)

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def list_tool_names(self) -> list[str]:
        """Return sorted list of registered tool names."""
        from harness_poc.system_tools import get_registry  # noqa: PLC0415

        self._ensure_discovered()
        return sorted(get_registry().keys())


# ------------------------------------------------------------------
# Internal: scan system_skills/ for type:tool entries
# ------------------------------------------------------------------

def _discover_tool_skills(
    skills_dir: Path,
    _skill_runner: SkillRunner | None,
) -> None:
    """Walk ``skills_dir`` and register any SKILL.md with ``type: tool``.

    These tool-level skills are registered in the built-in tool registry
    as skill-backed handlers.  Execution is delegated to ``SkillRunner``
    (which creates the proper ``SkillContext``).
    """
    if not skills_dir.exists():
        return

    import yaml  # noqa: PLC0415

    from harness_poc.system_tools import register as _register  # noqa: PLC0415

    for skill_file in sorted(skills_dir.glob("*/SKILL.md")):
        try:
            ftype, name, description, params = _parse_skill_frontmatter(
                skill_file, yaml
            )
        except (OSError, ValueError, TypeError, KeyError):
            logger.debug("Skipping unparseable skill: %s", skill_file)
            continue

        if ftype != "tool":
            continue

        # Register a skill-backed handler in the tool registry.
        # The actual execution is handled by ToolRunner.execute_tool()
        # which checks the _skill_backed flag.
        _register(
            name=name,
            description=description,
            parameters=params,
            handler=_make_skill_backed_stub(name),
            _skill_backed=True,
        )
        logger.debug("Registered skill-backed tool: %s", name)


def _parse_skill_frontmatter(
    skill_file: Path,
    yaml_module: Any,  # noqa: ANN401
) -> tuple[str, str, str, dict[str, Any]]:
    """Extract ``type``, ``name``, ``description``, and ``parameters``
    from a SKILL.md YAML frontmatter.

    Returns ``("skill", ...)`` with empty description/params on parse failure
    so callers can skip without crashing.
    """
    text = skill_file.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return ("skill", "", "", {})

    frontmatter_end = text.find("\n---", 3)
    if frontmatter_end == -1:
        return ("skill", "", "", {})

    frontmatter_text = text[3:frontmatter_end]
    parts = list(yaml_module.safe_load_all(frontmatter_text))
    fm = parts[0] if parts else {}
    if not isinstance(fm, dict):
        return ("skill", "", "", {})

    ftype = str(fm.get("type", "skill"))
    name = str(fm.get("name", ""))
    description = str(fm.get("description", ""))
    params = fm.get("parameters", {"type": "object", "properties": {}})
    if not isinstance(params, dict):
        params = {"type": "object", "properties": {}}

    return (ftype, name, description, params)


def _make_skill_backed_stub(name: str) -> Any:  # noqa: ANN401
    """Return a stub handler for a skill-backed tool.

    The stub is never called directly -- ``ToolRunner.execute_tool()``
    detects ``_skill_backed`` and routes to ``SkillRunner`` instead.
    It exists only so the tool registry entry is non-None.
    """

    def _stub(**kwargs: object) -> dict[str, Any]:  # noqa: ARG001
        msg = f"Skill-backed tool {name} was called through the stub. This is a bug."
        raise RuntimeError(msg)

    _stub.__name__ = f"_stub_{name}"
    return _stub
