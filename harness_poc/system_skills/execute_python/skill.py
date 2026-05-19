from __future__ import annotations

import base64
import json
from typing import Any

from harness_poc.core.skill_context import SkillContext, SkillResult
from harness_poc.system_skills.container_exec.skill import execute as execute_container_command
from harness_poc.system_skills.container_spawn.skill import execute as spawn_container

DEFAULT_TIMEOUT_SECONDS = 30
MAX_TIMEOUT_SECONDS = 300


def execute(ctx: SkillContext, arguments: dict[str, Any]) -> SkillResult:
    code = str(arguments.get("code") or "")
    if not code.strip():
        return SkillResult(
            status="failed",
            content="execute_python requires Python code.",
            artifacts={"error": "missing_code"},
        )

    container = str(arguments.get("container") or "").strip()
    image = str(arguments.get("image") or "").strip()
    workdir = str(arguments.get("workdir") or "").strip()
    timeout_seconds = _parse_timeout(arguments.get("timeout_seconds"))

    spawn_result: SkillResult | None = None
    if not container:
        container_name = f"harness-python-{ctx.session_id[:12]}"
        spawn_args: dict[str, Any] = {"container_name": container_name}
        if image:
            spawn_args["image"] = image
        spawn_result = spawn_container(ctx, spawn_args)
        if spawn_result.status != "success":
            return SkillResult(
                status=spawn_result.status,
                content=f"execute_python could not prepare a container: {spawn_result.content}",
                artifacts={
                    "error": "container_spawn_failed",
                    "spawn": spawn_result.artifacts,
                },
            )
        container = str(spawn_result.artifacts.get("container_name") or container_name)

    encoded = base64.b64encode(code.encode("utf-8")).decode("ascii")
    command = (
        "python -c "
        f"\"import base64; exec(compile(base64.b64decode('{encoded}'), "
        "'<execute_python>', 'exec'))\""
    )
    exec_result = execute_container_command(
        ctx,
        {
            "command": command,
            "container": container,
            "workdir": workdir,
            "timeout_seconds": timeout_seconds,
        },
    )

    artifacts = _merge_artifacts(
        exec_result.artifacts,
        code=code,
        container=container,
        timeout_seconds=timeout_seconds,
        spawn_result=spawn_result,
    )
    content = _format_content(artifacts)

    return SkillResult(
        status=exec_result.status,
        content=content,
        artifacts=artifacts,
    )


def _merge_artifacts(
    exec_artifacts: dict[str, Any],
    *,
    code: str,
    container: str,
    timeout_seconds: int,
    spawn_result: SkillResult | None,
) -> dict[str, Any]:
    artifacts = dict(exec_artifacts)
    artifacts["container"] = str(artifacts.get("container") or container)
    artifacts["timeout_seconds"] = timeout_seconds
    artifacts["code"] = code
    artifacts["spawned_container"] = spawn_result is not None
    if spawn_result is not None:
        artifacts["spawn"] = spawn_result.artifacts
    return artifacts


def _format_content(artifacts: dict[str, Any]) -> str:
    output = {
        "container": artifacts.get("container"),
        "backend": artifacts.get("backend"),
        "exit_code": artifacts.get("exit_code"),
        "stdout": artifacts.get("stdout", ""),
        "stderr": artifacts.get("stderr", ""),
        "timeout_seconds": artifacts.get("timeout_seconds"),
    }
    return json.dumps(output, indent=2, sort_keys=True)


def _parse_timeout(raw: object) -> int:
    try:
        timeout = int(str(raw))
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT_SECONDS
    return max(1, min(timeout, MAX_TIMEOUT_SECONDS))
