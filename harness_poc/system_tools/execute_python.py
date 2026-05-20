"""execute_python — run Python code inside a session container.

Migrated from ``system_skills/execute_python/skill.py`` (Phase 4).
Orchestrates container_spawn + container_exec internally.
"""

from __future__ import annotations

import base64
import json
from typing import Any

from harness_poc.core.skill_context import SkillResult
from harness_poc.core.tool_context import ToolContext
from harness_poc.system_tools.container_exec import container_exec
from harness_poc.system_tools.container_spawn import container_spawn

DEFAULT_TIMEOUT_SECONDS = 30
MAX_TIMEOUT_SECONDS = 300
MAX_STDOUT_CHARS = 20_000
MAX_STDERR_CHARS = 20_000


def execute_python(
    ctx: ToolContext,
    code: str = "",
    container: str = "",
    image: str = "",
    workdir: str = "",
    timeout_seconds: int | None = None,
) -> SkillResult:
    """Execute Python code inside a session-scoped container.

    CRITICAL: /workspace is READ-ONLY — write output files (images,
    charts, CSVs) to /scratch/, never to /workspace or the current
    directory.
    """
    code = (code or "").strip()
    if not code:
        return SkillResult(
            status="failed",
            content="execute_python requires Python code.",
            artifacts={"error": "missing_code"},
        )

    container = (container or "").strip()
    image = (image or "").strip()
    workdir = (workdir or "").strip()
    timeout = _parse_timeout(timeout_seconds)

    spawn_result: SkillResult | None = None
    if not container:
        container_name = f"harness-python-{ctx.session_id[:12]}"
        spawn_args: dict[str, Any] = {"container_name": container_name}
        if image:
            spawn_args["image"] = image
        spawn_result = container_spawn(ctx, **spawn_args)
        if spawn_result.status != "success":
            return SkillResult(
                status=spawn_result.status,
                content=(
                    "execute_python could not prepare a container: "
                    f"{spawn_result.content}"
                ),
                artifacts={
                    "error": "container_spawn_failed",
                    "spawn": spawn_result.artifacts,
                },
            )
        container = str(
            spawn_result.artifacts.get("container_name") or container_name
        )

    encoded = base64.b64encode(code.encode("utf-8")).decode("ascii")
    command = (
        "python -c "
        f"\"import base64; exec(compile(base64.b64decode('{encoded}'), "
        "'<execute_python>', 'exec'))\""
    )
    exec_result = container_exec(
        command=command,
        container=container,
        workdir=workdir,
        timeout_seconds=timeout,
    )

    artifacts = _merge_artifacts(
        exec_result.artifacts,
        code=code,
        container=container,
        timeout_seconds=timeout,
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
    stdout = str(artifacts.get("stdout", ""))
    stderr = str(artifacts.get("stderr", ""))
    artifacts["stdout_original_chars"] = len(stdout)
    artifacts["stdout_retained_chars"] = min(len(stdout), MAX_STDOUT_CHARS)
    artifacts["stdout_truncated"] = len(stdout) > MAX_STDOUT_CHARS
    artifacts["stderr_original_chars"] = len(stderr)
    artifacts["stderr_retained_chars"] = min(len(stderr), MAX_STDERR_CHARS)
    artifacts["stderr_truncated"] = len(stderr) > MAX_STDERR_CHARS
    if spawn_result is not None:
        artifacts["spawn"] = spawn_result.artifacts
    return artifacts


def _format_content(artifacts: dict[str, Any]) -> str:
    stdout, _stdout_meta = _cap_stream(
        str(artifacts.get("stdout", "")), MAX_STDOUT_CHARS
    )
    stderr, _stderr_meta = _cap_stream(
        str(artifacts.get("stderr", "")), MAX_STDERR_CHARS
    )
    output = {
        "container": artifacts.get("container"),
        "backend": artifacts.get("backend"),
        "exit_code": artifacts.get("exit_code"),
        "stdout": stdout,
        "stderr": stderr,
        "timeout_seconds": artifacts.get("timeout_seconds"),
        "stdout_original_chars": artifacts.get(
            "stdout_original_chars", len(stdout)
        ),
        "stdout_retained_chars": artifacts.get(
            "stdout_retained_chars", len(stdout)
        ),
        "stdout_truncated": artifacts.get("stdout_truncated", False),
        "stderr_original_chars": artifacts.get(
            "stderr_original_chars", len(stderr)
        ),
        "stderr_retained_chars": artifacts.get(
            "stderr_retained_chars", len(stderr)
        ),
        "stderr_truncated": artifacts.get("stderr_truncated", False),
    }
    return json.dumps(output, indent=2, sort_keys=True)


def _parse_timeout(raw: int | float | None) -> int:
    if raw is None:
        return DEFAULT_TIMEOUT_SECONDS
    try:
        timeout = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT_SECONDS
    return max(1, min(timeout, MAX_TIMEOUT_SECONDS))


def _cap_stream(
    text: str, max_chars: int
) -> tuple[str, dict[str, int | bool]]:
    original_chars = len(text)
    if original_chars <= max_chars:
        return text, {
            "original_chars": original_chars,
            "retained_chars": original_chars,
            "truncated": False,
        }

    notice = (
        f"\n[execute_python output truncated: original_chars={original_chars} "
        f"retained_chars={max_chars}]"
    )
    return text[:max_chars] + notice, {
        "original_chars": original_chars,
        "retained_chars": max_chars,
        "truncated": True,
    }


# ── Register ──────────────────────────────────────────────────────────

from harness_poc.system_tools import register as _register  # noqa: E402

_register(
    name="execute_python",
    description=(
        "Executes Python code inside a session-scoped container. "
        "CRITICAL: /workspace is READ-ONLY — write output files "
        "(images, charts, CSVs) to /scratch/, never to /workspace "
        "or the current directory."
    ),
    parameters={
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "Python source code to execute.",
            },
            "container": {
                "type": "string",
                "description": (
                    "Container name or ID. If omitted, a new container "
                    "is spawned automatically."
                ),
            },
            "image": {
                "type": "string",
                "description": "Container image (only used when spawning).",
            },
            "workdir": {
                "type": "string",
                "description": (
                    "Working directory inside the container "
                    "(relative to /workspace)."
                ),
            },
            "timeout_seconds": {
                "type": "integer",
                "description": (
                    "Max execution time in seconds "
                    f"(default: {DEFAULT_TIMEOUT_SECONDS}, "
                    f"max: {MAX_TIMEOUT_SECONDS})."
                ),
            },
        },
        "required": ["code"],
    },
    handler=execute_python,
)
