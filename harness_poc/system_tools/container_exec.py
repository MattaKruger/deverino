"""container_exec — run a command inside a session container.

Migrated from ``system_skills/container_exec/skill.py`` (Phase 4).
Takes no ``ToolContext`` — this is a pure subprocess wrapper.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from typing import Any

from harness_poc.core.skill_context import SkillResult

BACKENDS = ("podman", "docker")
DEFAULT_TIMEOUT_SECONDS = 120
MAX_TIMEOUT_SECONDS = 300
logger = logging.getLogger(__name__)


def container_exec(
    command: str = "",
    container: str = "",
    backend: str = "auto",
    workdir: str = "",
    timeout_seconds: int | None = None,
) -> SkillResult:
    """Run a command inside an existing container."""
    command = (command or "").strip()
    container = (container or "").strip()
    backend_arg = (backend or "auto").strip().lower()
    workdir = (workdir or "").strip()
    timeout = _parse_timeout(timeout_seconds)

    if not command:
        logger.error("Container exec missing command")
        return SkillResult(status="failed", content="container_exec requires a command")
    if not container:
        logger.error("Container exec missing container")
        return SkillResult(
            status="failed",
            content="container_exec requires a container name or ID",
        )

    resolved_backend = _resolve_backend(backend_arg)
    if resolved_backend is None:
        available = [b for b in BACKENDS if shutil.which(b)]
        logger.error(
            "Container exec backend resolution failed",
            extra={"backend_arg": backend_arg, "available": available},
        )
        return SkillResult(
            status="failed",
            content=(
                "No container runtime found. "
                f"Tried: {', '.join(BACKENDS)}. "
                f"Available on PATH: {', '.join(available) if available else 'none'}."
            ),
        )

    exec_cmd = [resolved_backend, "exec"]
    if workdir:
        exec_cmd.extend(["-w", f"/workspace/{workdir}"])
    exec_cmd.append(container)
    exec_cmd.extend(["sh", "-c", command])
    logger.info(
        "Executing command in container",
        extra={
            "backend": resolved_backend,
            "container": container,
            "workdir": workdir,
            "command": command,
        },
    )

    try:
        result = subprocess.run(  # noqa: S603
            exec_cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        logger.exception(
            "Container exec timed out",
            extra={
                "backend": resolved_backend,
                "container": container,
                "command": command,
            },
        )
        return SkillResult(
            status="failed",
            content=f"Command timed out after {timeout}s in container '{container}'.",
            artifacts={
                "backend": resolved_backend,
                "container": container,
                "timeout_seconds": timeout,
            },
        )
    except OSError as exc:
        logger.exception(
            "Container runtime invocation failed",
            extra={
                "backend": resolved_backend,
                "container": container,
                "command": command,
            },
        )
        return SkillResult(
            status="failed",
            content=f"Failed to invoke {resolved_backend}: {exc}",
            artifacts={
                "backend": resolved_backend,
                "container": container,
            },
        )

    output: dict[str, Any] = {
        "backend": resolved_backend,
        "container": container,
        "command": command,
        "exit_code": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
        "timeout_seconds": timeout,
    }
    status: str = "success" if result.returncode == 0 else "failed"

    return SkillResult(
        status=status,  # type: ignore[arg-type]
        content=json.dumps(output, indent=2, sort_keys=True),
        artifacts=output,
    )


def _resolve_backend(backend_arg: str) -> str | None:
    if backend_arg in BACKENDS:
        if shutil.which(backend_arg):
            return backend_arg
        return None
    for b in BACKENDS:
        if shutil.which(b):
            return b
    return None


def _parse_timeout(raw: int | float | None) -> int:
    if raw is None:
        return DEFAULT_TIMEOUT_SECONDS
    try:
        timeout = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT_SECONDS
    return max(1, min(timeout, MAX_TIMEOUT_SECONDS))


# ── Register ──────────────────────────────────────────────────────────

from harness_poc.system_tools import register as _register  # noqa: E402

_register(
    name="container_exec",
    description=(
        "Executes a shell command inside a container (Podman, Docker, or "
        "auto-detected backend). The container must already exist — use "
        "container_spawn first."
    ),
    parameters={
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The shell command to execute inside the container.",
            },
            "container": {
                "type": "string",
                "description": "Container name or ID.",
            },
            "backend": {
                "type": "string",
                "description": "Container runtime: podman, docker, or auto.",
                "enum": ["podman", "docker", "auto"],
                "default": "auto",
            },
            "workdir": {
                "type": "string",
                "description": "Working directory inside the container (relative to /workspace).",
            },
            "timeout_seconds": {
                "type": "integer",
                "description": f"Max execution time in seconds (default: {DEFAULT_TIMEOUT_SECONDS}, max: {MAX_TIMEOUT_SECONDS}).",
            },
        },
        "required": ["command", "container"],
    },
    handler=container_exec,
)
