from __future__ import annotations

import contextlib
import json
import shutil
import subprocess
from typing import Any

from harness_poc.core.skill_context import SkillContext, SkillResult

BACKENDS = ("podman", "docker")


def execute(ctx: SkillContext, arguments: dict[str, Any]) -> SkillResult:
    container = str(arguments.get("container") or "").strip()
    if not container:
        return SkillResult(
            status="failed",
            content="container_destroy requires a container name",
        )

    backend = _resolve_backend()
    if backend is None:
        return SkillResult(
            status="failed",
            content=f"No container runtime found. Tried: {', '.join(BACKENDS)}.",
        )

    # Stop (best-effort, may already be stopped)
    subprocess.run(  # noqa: S603
        [backend, "stop", container],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    # Remove
    try:
        rm_result = subprocess.run(  # noqa: S603
            [backend, "rm", container],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return SkillResult(
            status="failed",
            content=f"Failed to remove container '{container}': {exc}",
            artifacts={"backend": backend, "container": container},
        )

    # Clear blackboard entry
    with contextlib.suppress(OSError, ValueError, RuntimeError):
        ctx.database.write_memory(ctx.session_id, f"container.{container}", {"removed": True})

    output: dict[str, Any] = {
        "backend": backend,
        "container": container,
        "removed": rm_result.returncode == 0,
        "stderr": rm_result.stderr.strip() if rm_result.returncode != 0 else "",
    }

    return SkillResult(
        status="success" if output["removed"] else "failed",
        content=json.dumps(output, indent=2, sort_keys=True),
        artifacts=output,
    )


def _resolve_backend() -> str | None:
    for backend in BACKENDS:
        if shutil.which(backend):
            return backend
    return None
