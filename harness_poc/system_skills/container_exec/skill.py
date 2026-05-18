from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any

from harness_poc.core.skill_context import SkillContext, SkillResult

BACKENDS = ("podman", "docker")


def execute(ctx: SkillContext, arguments: dict[str, Any]) -> SkillResult:
    del ctx

    command = str(arguments.get("command") or "").strip()
    container = str(arguments.get("container") or "").strip()
    backend_arg = str(arguments.get("backend") or "auto").strip().lower()
    workdir = str(arguments.get("workdir") or "").strip()

    if not command:
        return SkillResult(
            status="failed", content="container_exec requires a command"
        )
    if not container:
        return SkillResult(
            status="failed",
            content="container_exec requires a container name or ID",
        )

    backend = _resolve_backend(backend_arg)
    if backend is None:
        available = [b for b in BACKENDS if shutil.which(b)]
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

    try:
        result = subprocess.run(  # noqa: S603
            exec_cmd,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return SkillResult(
            status="failed",
            content=f"Command timed out after 120s in container '{container}'.",
            artifacts={"backend": backend, "container": container},
        )
    except OSError as exc:
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
    for backend in BACKENDS:
        if shutil.which(backend):
            return backend
    return None
