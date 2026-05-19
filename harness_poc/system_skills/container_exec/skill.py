from __future__ import annotations

import json
import logging
import shutil
import subprocess
from typing import Any

from harness_poc.core.skill_context import SkillContext, SkillResult

BACKENDS = ("podman", "docker")
DEFAULT_TIMEOUT_SECONDS = 120
MAX_TIMEOUT_SECONDS = 300
logger = logging.getLogger(__name__)


def execute(ctx: SkillContext, arguments: dict[str, Any]) -> SkillResult:
    del ctx

    command = str(arguments.get("command") or "").strip()
    container = str(arguments.get("container") or "").strip()
    backend_arg = str(arguments.get("backend") or "auto").strip().lower()
    workdir = str(arguments.get("workdir") or "").strip()
    timeout_seconds = _parse_timeout(arguments.get("timeout_seconds"))

    if not command:
        logger.error("Container exec missing command")
        return SkillResult(status="failed", content="container_exec requires a command")
    if not container:
        logger.error("Container exec missing container")
        return SkillResult(
            status="failed",
            content="container_exec requires a container name or ID",
        )

    backend = _resolve_backend(backend_arg)
    if backend is None:
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

    exec_cmd = [backend, "exec"]
    if workdir:
        exec_cmd.extend(["-w", f"/workspace/{workdir}"])
    exec_cmd.append(container)
    exec_cmd.extend(["sh", "-c", command])
    logger.info(
        "Executing command in container",
        extra={
            "backend": backend,
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
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired:
        logger.exception(
            "Container exec timed out",
            extra={
                "backend": backend,
                "container": container,
                "command": command,
            },
        )
        return SkillResult(
            status="failed",
            content=f"Command timed out after {timeout_seconds}s in container '{container}'.",
            artifacts={
                "backend": backend,
                "container": container,
                "timeout_seconds": timeout_seconds,
            },
        )
    except OSError as exc:
        logger.exception(
            "Container runtime invocation failed",
            extra={
                "backend": backend,
                "container": container,
                "command": command,
            },
        )
        return SkillResult(
            status="failed",
            content=f"Failed to invoke {backend}: {exc}",
            artifacts={"backend": backend, "container": container},
        )

    output = {
        "backend": backend,
        "container": container,
        "command": command,
        "exit_code": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
        "timeout_seconds": timeout_seconds,
    }
    status: str = "success" if result.returncode == 0 else "failed"
    if result.returncode == 0:
        logger.debug(
            "Container exec completed",
            extra={
                "backend": backend,
                "container": container,
                "command": command,
            },
        )
    else:
        logger.error(
            "Container exec failed",
            extra={
                "backend": backend,
                "container": container,
                "command": command,
                "exit_code": result.returncode,
                "stderr": result.stderr.strip(),
            },
        )

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
    for backend in BACKENDS:
        if shutil.which(backend):
            return backend
    return None


def _parse_timeout(raw: object) -> int:
    try:
        timeout = int(str(raw))
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT_SECONDS
    return max(1, min(timeout, MAX_TIMEOUT_SECONDS))
