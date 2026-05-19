from __future__ import annotations

import importlib.util
import logging
from typing import TYPE_CHECKING, Any, TypedDict, cast

import yaml

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path
    from types import ModuleType

    from harness_poc.core.config import HarnessConfig
    from harness_poc.core.database import BlackboardDatabase
    from harness_poc.core.skill_context import SkillResult

from harness_poc.core.skill_context import SkillContext
from harness_poc.core.permissions import SkillPermissions
from harness_poc.core.blackboard_proxy import BlackboardAccessProxy

logger = logging.getLogger(__name__)


class SkillMetadata(TypedDict):
    name: str
    description: str
    parameters: dict[str, Any]
    auto_invokable: bool
    permissions: dict[str, str]


class ToolSchema(TypedDict):
    type: str
    function: SkillMetadata


class SkillDocument(TypedDict):
    metadata: SkillMetadata
    body: str
    path: Path
    entrypoint: dict[str, str]


class SkillRunner:
    def __init__(
        self,
        database: BlackboardDatabase,
        config: HarnessConfig,
    ) -> None:
        self.database = database
        self.config = config
        self.skills_dirs: tuple[Path, Path] = (
            config.paths.system_skills,
            config.paths.project_skills,
        )

    def discover_skills(self) -> list[dict[str, Any]]:
        tools: list[dict[str, Any]] = []
        seen: set[str] = set()
        for skills_dir in self.skills_dirs:
            if not skills_dir.exists():
                continue
            for skill_file in sorted(skills_dir.glob("*/SKILL.md")):
                skill = self.parse_skill_document(skill_file)
                skill_name = skill["metadata"]["name"]
                if skill_name in seen:
                    continue
                seen.add(skill_name)

                tools.append(
                    {
                        "type": "function",
                        "function": {
                            "name": skill_name,
                            "description": skill["metadata"]["description"],
                            "parameters": skill["metadata"]["parameters"],
                            "auto_invokable": skill["metadata"]["auto_invokable"],
                            "permissions": skill["metadata"]["permissions"],
                        },
                    },
                )

        logger.debug("Discovered skills", extra={"count": len(tools)})

        return tools

    def execute_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        session_id: str,
    ) -> str:
        result = self.execute_skill(
            tool_name=tool_name,
            arguments=arguments,
            session_id=session_id,
        )

        return result.content

    def execute_skill(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        session_id: str,
        on_text: Callable[[str], None] | None = None,
        on_tool_event: Callable[[str], None] | None = None,
    ) -> SkillResult:
        resolved_tool_name = self._resolve_alias(tool_name)
        logger.debug(
            "Executing skill",
            extra={
                "tool_name": tool_name,
                "resolved_tool_name": resolved_tool_name,
                "session_id": session_id,
                "arguments": arguments,
            },
        )
        try:
            skill_file = self._find_skill_file(resolved_tool_name)
            skill = self.parse_skill_document(skill_file)
            skill_permissions = SkillPermissions.from_yaml(
                skill["metadata"].get("permissions", {})
            )
            execute = self._load_entrypoint(skill)

            context = SkillContext(
                session_id=session_id,
                skill_name=resolved_tool_name,
                database=BlackboardAccessProxy(self.database, skill_permissions),
                config=self.config,
                permissions=skill_permissions,
                stream_text=on_text,
                on_tool_event=on_tool_event,
            )
            normalized_arguments = self._normalize_arguments(resolved_tool_name, arguments)

            result = execute(context, normalized_arguments)
        except Exception:
            logger.exception(
                "Skill execution raised",
                extra={
                    "tool_name": tool_name,
                    "resolved_tool_name": resolved_tool_name,
                    "session_id": session_id,
                },
            )
            raise

        if result.status == "success":
            logger.debug(
                "Skill execution completed",
                extra={
                    "tool_name": resolved_tool_name,
                    "session_id": session_id,
                    "status": result.status,
                },
            )
        else:
            logger.error(
                "Skill execution returned non-success status",
                extra={
                    "tool_name": resolved_tool_name,
                    "session_id": session_id,
                    "status": result.status,
                    "content": result.content,
                    "artifacts": result.artifacts,
                },
            )

        return result

    def _find_skill_file(self, tool_name: str) -> Path:
        for skills_dir in self.skills_dirs:
            if not skills_dir.exists():
                continue
            for skill_file in sorted(skills_dir.glob("*/SKILL.md")):
                skill = self.parse_skill_document(skill_file)
                if skill["metadata"]["name"] == tool_name:
                    return skill_file
        msg = f"Unknown skill requested: {tool_name}"
        raise ValueError(msg)

    @staticmethod
    def _resolve_alias(tool_name: str) -> str:
        aliases = {
            "delegate_to_subagent": "delegate_task",
            "read_global_context": "read_memory",
        }

        return aliases.get(tool_name, tool_name)

    @staticmethod
    def _normalize_arguments(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(arguments)
        if (
            tool_name == "delegate_task"
            and "template_name" in normalized
            and "persona" not in normalized
        ):
            normalized["persona"] = normalized["template_name"]

        return normalized

    @staticmethod
    def _load_entrypoint(
        skill: SkillDocument,
    ) -> Callable[[SkillContext, dict[str, Any]], SkillResult]:
        entrypoint = skill["entrypoint"]
        module_name = entrypoint["module"]
        function_name = entrypoint["function"]
        module_path = skill["path"].parent / f"{module_name}.py"
        if not module_path.exists():
            msg = f"Skill entrypoint file not found: {module_path}"
            raise FileNotFoundError(msg)

        spec = importlib.util.spec_from_file_location(
            f"harness_skill_{skill['metadata']['name']}",
            module_path,
        )
        if spec is None or spec.loader is None:
            msg = f"Could not load skill module: {module_path}"
            raise ImportError(msg)
        module = importlib.util.module_from_spec(spec)
        loader = spec.loader
        loader.exec_module(module)

        return _get_execute_function(module, function_name)

    @staticmethod
    def parse_skill_document(skill_file: Path) -> SkillDocument:
        text = skill_file.read_text(encoding="utf-8")
        if not text.startswith("---"):
            msg = f"Skill {skill_file} must start with YAML frontmatter"
            raise ValueError(msg)

        frontmatter_end = text.find("\n---", 3)
        if frontmatter_end == -1:
            msg = f"Skill {skill_file} must close YAML frontmatter"
            raise ValueError(msg)

        frontmatter_text = text[3:frontmatter_end]
        body = text[frontmatter_end + 4 :].strip()
        parts = list(yaml.safe_load_all(frontmatter_text))
        frontmatter = parts[0] if parts else {}
        if not isinstance(frontmatter, dict):
            msg = f"Invalid YAML frontmatter in {skill_file}"
            raise TypeError(msg)

        name = frontmatter.get("name")
        description = frontmatter.get("description")
        parameters = frontmatter.get("parameters", {"type": "object", "properties": {}})
        entrypoint = frontmatter.get("entrypoint", {"module": "skill", "function": "execute"})
        auto_invokable = bool(frontmatter.get("auto_invokable", False))
        raw_permissions = frontmatter.get("permissions", {})
        permissions: dict[str, str] = (
            raw_permissions if isinstance(raw_permissions, dict) else {}
        )
        if not isinstance(name, str) or not isinstance(description, str):
            msg = f"Skill {skill_file} must define string name and description"
            raise TypeError(msg)
        if not isinstance(parameters, dict):
            msg = f"Skill {skill_file} parameters must be a mapping"
            raise TypeError(msg)
        if not isinstance(entrypoint, dict):
            msg = f"Skill {skill_file} entrypoint must be a mapping"
            raise TypeError(msg)

        entrypoint_module = entrypoint.get("module", "skill")
        entrypoint_function = entrypoint.get("function", "execute")
        if not isinstance(entrypoint_module, str) or not isinstance(entrypoint_function, str):
            msg = f"Skill {skill_file} entrypoint module and function must be strings"
            raise TypeError(msg)

        return {
            "metadata": {
                "name": name,
                "description": description,
                "parameters": cast("dict[str, Any]", parameters),
                "auto_invokable": auto_invokable,
                "permissions": permissions,
            },
            "body": body,
            "path": skill_file,
            "entrypoint": {
                "module": entrypoint_module,
                "function": entrypoint_function,
            },
        }


def _get_execute_function(
    module: ModuleType,
    function_name: str,
) -> Callable[[SkillContext, dict[str, Any]], SkillResult]:
    execute = getattr(module, function_name, None)
    if not callable(execute):
        msg = f"Skill module does not define callable {function_name}"
        raise TypeError(msg)
    return cast("Callable[[SkillContext, dict[str, Any]], SkillResult]", execute)
