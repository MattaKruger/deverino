"""ToolRunner -- discovers and executes built-in (LLM-callable) tools.

Mirrors ``SkillRunner`` in shape but is simpler for built-in tools: those
have no SKILL.md, no permissions, no YAML frontmatter. They register
themselves at import time via ``harness_poc.system_tools.register()``.

Built-in tools are pure functions -- no sub-agent spawning, no LLM
involvement. They correspond to Hermes's ``tools/`` layer.

ToolRunner also scans ``project_skills/`` for SKILL.md files with
``type: tool``. Those tool-level skills are executed through
``SkillRunner`` (which creates a proper ``SkillContext``).
"""

from __future__ import annotations

import importlib.util
import inspect
import json as _json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any, cast

from harness_poc.core.skill_context import CancellationToken, SkillResult, SkillStatus
from harness_poc.core.tool_context import ToolContext
from harness_poc.core.tool_result import ToolResult

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from harness_poc.core.config import HarnessConfig, RuntimeConfig
    from harness_poc.core.skill_runner import SkillRunner
    from harness_poc.core.storage import BlackboardAccessProxy

logger = logging.getLogger(__name__)
_CANCELLABLE_TOOL_NAMES = frozenset({"container_exec", "execute_python"})
_CANCELLATION_POLL_S = 0.05


class ToolRunner:
    """Discover and execute built-in tools.

    Handlers may optionally accept a ``ToolContext`` as their first
    parameter.  ``ToolRunner`` inspects the signature and injects it
    when needed, so pure tools stay pure and context-aware tools get
    what they need.
    """

    def __init__(
        self,
        config: HarnessConfig,
        *,
        skill_runner: SkillRunner | None = None,
        database: BlackboardAccessProxy | None = None,
        runtime_config: RuntimeConfig | None = None,
    ) -> None:
        self._tools_dir: Path = config.paths.system_tools
        self._project_skills_dir: Path = config.paths.project_skills
        self._project_root: Path = config.project_root
        self._skill_runner: SkillRunner | None = skill_runner
        self._database: BlackboardAccessProxy | None = database
        self._runtime_config: RuntimeConfig | None = runtime_config
        self._discovered = False
        self._active_tokens: dict[str, CancellationToken] = {}

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def _ensure_discovered(self) -> None:
        """Import tool modules + scan project_skills/ for type:tool skills."""
        if self._discovered:
            return

        # 1. Built-in tools from system_tools/ — use standard imports
        #    so monkeypatching in tests works (importlib spec_from_file_location
        #    creates separate module objects).
        if self._tools_dir.exists():
            for py_file in sorted(self._tools_dir.glob("*.py")):
                if py_file.name.startswith("_"):
                    continue
                module_name = f"harness_poc.system_tools.{py_file.stem}"
                try:
                    importlib.import_module(module_name)
                except Exception:
                    logger.exception("Failed to load tool module: %s", py_file)

        # 2. Tool-level skills from project_skills/ (SKILL.md with type: tool)
        # These are still skill-backed — their code lives in skills/*/skill.py.
        _discover_tool_skills(self._project_skills_dir, self._skill_runner)

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

    def execute_tool(  # noqa: PLR0911
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        session_id: str = "",
        call_id: str | None = None,
        cancellation: CancellationToken | None = None,
    ) -> str:
        """Execute a tool and return its JSON-serialized result.

        For skill-backed tools (discovered from project_skills/), the
        ``session_id`` is forwarded to ``SkillRunner.execute_skill()``.
        Built-in tools that accept a ``ToolContext`` get one injected
        with the current session info.
        """
        from harness_poc.system_tools import get_registry  # noqa: PLC0415

        self._ensure_discovered()
        info = get_registry().get(tool_name)
        if info is None:
            return _json.dumps({"error": f"Unknown tool: {tool_name}"})

        handler = cast("Callable[..., object]", info["handler"])
        token = cancellation or CancellationToken()
        if call_id is not None:
            self._active_tokens[call_id] = token

        try:
            # Skill-backed tools (from project_skills/) route through SkillRunner
            if info.get("_skill_backed") and self._skill_runner is not None:
                result = self._skill_runner.execute_skill(
                    tool_name=tool_name,
                    arguments=arguments,
                    session_id=session_id,
                    call_id=call_id,
                    cancellation=token,
                )
                return _json.dumps(result.to_dict(), ensure_ascii=False)

            # Built-in tools — inject ToolContext if the handler accepts it
            kwargs = dict(arguments)
            if _accepts_cancellation(handler):
                kwargs["cancellation"] = token
            if _accepts_context(handler):
                ctx = ToolContext(
                    session_id=session_id,
                    project_root=self._project_root,
                    database=self._database,
                    runtime_config=self._runtime_config,
                    cancellation=token,
                )
                result = self._execute_handler(tool_name, handler, token, ctx, **kwargs)
            else:
                result = self._execute_handler(tool_name, handler, token, **kwargs)
        except TypeError as e:
            return _json.dumps({"error": f"Invalid arguments for {tool_name}: {e}"})
        except Exception:
            logger.exception("Tool execution failed: %s", tool_name)
            return _json.dumps({"error": f"Tool {tool_name} raised an unexpected error."})
        finally:
            if call_id is not None:
                self._active_tokens.pop(call_id, None)

        if isinstance(result, ToolResult):
            return _json.dumps(result.to_dict(), ensure_ascii=False)

        # SkillResult (from migrated tools still using the skill context module)
        if hasattr(result, "to_dict"):
            return _json.dumps(result.to_dict(), ensure_ascii=False)

        return _json.dumps(result, ensure_ascii=False)

    def cancel_call(self, call_id: str, reason: str) -> None:
        token = self._active_tokens.get(call_id)
        if token is not None:
            token.cancel(reason)

    def _execute_handler(
        self,
        tool_name: str,
        handler: Callable[..., object],
        token: CancellationToken,
        *args: Any,  # noqa: ANN401
        **kwargs: Any,  # noqa: ANN401
    ) -> Any:  # noqa: ANN401
        if tool_name not in _CANCELLABLE_TOOL_NAMES:
            return handler(*args, **kwargs)
        return _execute_with_token(handler, token, *args, **kwargs)

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def list_tool_names(self) -> list[str]:
        """Return sorted list of registered tool names."""
        from harness_poc.system_tools import get_registry  # noqa: PLC0415

        self._ensure_discovered()
        return sorted(get_registry().keys())


# ------------------------------------------------------------------
# Internal: scan project_skills/ for type:tool entries
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
            ftype, name, description, params = _parse_skill_frontmatter(skill_file, yaml)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            logger.debug("Skipping unparseable skill: %s (%s)", skill_file, exc)
            continue

        if ftype != "tool":
            continue

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
    """Extract fields from a SKILL.md YAML frontmatter."""
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

    The stub is never called directly — ``ToolRunner.execute_tool()``
    detects ``_skill_backed`` and routes to ``SkillRunner`` instead.
    """

    def _stub(**kwargs: object) -> dict[str, Any]:  # noqa: ARG001
        msg = f"Skill-backed tool {name} was called through the stub. This is a bug."
        raise RuntimeError(msg)

    _stub.__name__ = f"_stub_{name}"
    return _stub


def _accepts_context(handler: object) -> bool:
    """Return True if ``handler`` accepts a ``ToolContext`` first argument."""
    try:
        sig = inspect.signature(cast("Callable[..., object]", handler))
    except (ValueError, TypeError):
        return False
    params = list(sig.parameters.values())
    if not params:
        return False
    first = params[0]
    ann = first.annotation
    if ann is inspect.Parameter.empty:
        return first.name == "ctx"
    # Handle string annotations (PEP 563: from __future__ import annotations)
    if isinstance(ann, str):
        return ann == "ToolContext"
    return getattr(ann, "__name__", "") == "ToolContext"


def _accepts_cancellation(handler: object) -> bool:
    try:
        sig = inspect.signature(cast("Callable[..., object]", handler))
    except (ValueError, TypeError):
        return False
    return "cancellation" in sig.parameters


def _execute_with_token(
    fn: Callable[..., object],
    token: CancellationToken,
    *args: Any,  # noqa: ANN401
    **kwargs: Any,  # noqa: ANN401
) -> SkillResult:
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tool-runner")
    future = executor.submit(fn, *args, **kwargs)
    try:
        while not future.done():
            if token.cancelled:
                future.cancel()
                executor.shutdown(wait=False, cancel_futures=True)
                return SkillResult(
                    status="cancelled",
                    content=f"cancelled: {token.reason}",
                    artifacts={},
                )
            time.sleep(_CANCELLATION_POLL_S)
        result = future.result()
        if isinstance(result, SkillResult):
            return result
        if isinstance(result, ToolResult):
            return SkillResult(
                status="success",
                content=_json.dumps(result.to_dict(), ensure_ascii=False),
                artifacts=result.to_dict(),
            )
        to_dict = getattr(result, "to_dict", None)
        if callable(to_dict):
            data = to_dict()
            raw_status = data.get("status") or "success"
            status: SkillStatus = (
                cast("SkillStatus", raw_status)
                if raw_status
                in {"success", "failed", "blocked", "cancelled", "needs_orchestrator_action"}
                else "success"
            )
            return SkillResult(
                status=status,
                content=str(data.get("content") or data),
                artifacts=data.get("artifacts") if isinstance(data.get("artifacts"), dict) else {},
            )
        return SkillResult(status="success", content=_json.dumps(result, ensure_ascii=False))
    finally:
        if future.done():
            executor.shutdown(wait=False)
