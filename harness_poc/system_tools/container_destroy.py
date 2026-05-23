"""container_destroy — stop and remove a session container.

Migrated from ``system_skills/container_destroy/skill.py`` (Phase 4).
"""

from __future__ import annotations

import contextlib
import json
import shutil
import subprocess
from typing import Any

from harness_poc.core.skills import SkillResult
from harness_poc.core.tools import ToolContext

BACKENDS = ("podman", "docker")


def container_destroy(
    ctx: ToolContext,
    container: str = "",
) -> SkillResult:
    """Stop and remove a container. Cleans up the blackboard entry."""
    container = (container or "").strip()
    if not container:
        return SkillResult(
            status="failed",
            content="container_destroy requires a container name",
        )

    backend = _resolve_backend()
    if backend is None:
        return SkillResult(
            status="failed",
            content=(f"No container runtime found. Tried: {', '.join(BACKENDS)}."),
        )

    # Stop (best-effort)
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
    if ctx.database is not None:
        with contextlib.suppress(OSError, ValueError, RuntimeError):
            ctx.database.write_memory(
                ctx.session_id,
                f"container.{container}",
                {"removed": True},
            )

    # Clean up session scratch directory
    scratch_dir = ctx.project_root / ".deverino-scratch" / ctx.session_id
    if scratch_dir.exists():
        shutil.rmtree(scratch_dir, ignore_errors=True)

    output: dict[str, Any] = {
        "backend": backend,
        "container": container,
        "removed": rm_result.returncode == 0,
        "stderr": (rm_result.stderr.strip() if rm_result.returncode != 0 else ""),
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


# ── Register ──────────────────────────────────────────────────────────

from harness_poc.system_tools import register as _register  # noqa: E402

_register(
    name="container_destroy",
    description=("Stops and removes a container. Cleans up the blackboard memory entry."),
    parameters={
        "type": "object",
        "properties": {
            "container": {
                "type": "string",
                "description": "Container name or ID to destroy.",
            },
        },
        "required": ["container"],
    },
    handler=container_destroy,
)
