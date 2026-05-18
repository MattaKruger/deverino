from __future__ import annotations

import json
import logging
import shutil
import subprocess
import time
from typing import Any, cast

from harness_poc.core.skill_context import SkillContext, SkillResult

BACKENDS = ("podman", "docker")
KEEPALIVE_CMD: list[str] = ["sleep", "infinity"]
logger = logging.getLogger(__name__)


def execute(ctx: SkillContext, arguments: dict[str, Any]) -> SkillResult:  # noqa: PLR0911
    session_id = ctx.session_id
    image = str(
        arguments.get("image") or ctx.config.runtime.default_container_image or ""
    ).strip()
    container_name = str(
        arguments.get("container_name") or f"harness-{session_id[:12]}"
    ).strip()
    backend = _resolve_backend()

    error = _validate_inputs(image, backend)
    if error:
        logger.error(
            "Container spawn input validation failed",
            extra={
                "session_id": session_id,
                "image": image,
                "container_name": container_name,
                "backend": backend,
                "error": error,
            },
        )
        return SkillResult(status="failed", content=error)
    backend = cast("str", backend)  # validated above

    # Idempotent: check if container already exists
    existing = _inspect_container(backend, container_name)
    if existing:
        logger.info(
            "Container already exists",
            extra={
                "session_id": session_id,
                "container_name": container_name,
                "backend": backend,
            },
        )
        ctx.database.write_memory(session_id, f"container.{container_name}", existing)
        return SkillResult(
            status="success",
            content=json.dumps(existing, indent=2, sort_keys=True),
            artifacts=existing,
        )

    # Create the container
    project_root = str(ctx.project_root.resolve())
    create_cmd: list[str] = [
        backend,
        "run",
        "-d",
        "--name",
        container_name,
        "-v",
        f"{project_root}:/workspace",
        "-w",
        "/workspace",
        image,
    ]
    create_cmd.extend(KEEPALIVE_CMD)
    logger.info(
        "Creating container",
        extra={
            "session_id": session_id,
            "backend": backend,
            "image": image,
            "container_name": container_name,
        },
    )

    try:
        result = subprocess.run(  # noqa: S603
            create_cmd,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except subprocess.TimeoutExpired:
        logger.exception(
            "Container creation timed out",
            extra={
                "session_id": session_id,
                "backend": backend,
                "image": image,
                "container_name": container_name,
            },
        )
        return SkillResult(
            status="failed",
            content=f"Container creation timed out for image '{image}'.",
            artifacts={
                "backend": backend,
                "image": image,
                "container_name": container_name,
            },
        )
    except OSError as exc:
        logger.exception(
            "Container runtime invocation failed",
            extra={
                "session_id": session_id,
                "backend": backend,
                "image": image,
                "container_name": container_name,
            },
        )
        return SkillResult(
            status="failed",
            content=f"Failed to invoke {backend}: {exc}",
            artifacts={
                "backend": backend,
                "image": image,
                "container_name": container_name,
            },
        )

    if result.returncode != 0:
        logger.error(
            "Container creation failed",
            extra={
                "session_id": session_id,
                "backend": backend,
                "image": image,
                "container_name": container_name,
                "exit_code": result.returncode,
                "stderr": result.stderr.strip(),
            },
        )
        return SkillResult(
            status="failed",
            content=(
                f"Failed to create container '{container_name}': "
                f"{result.stderr.strip()}"
            ),
            artifacts={
                "backend": backend,
                "image": image,
                "container_name": container_name,
                "exit_code": result.returncode,
            },
        )

    container_id = result.stdout.strip()

    # Wait for container to actually start (macOS Docker Desktop can lag)
    for _attempt in range(10):
        info = _inspect_container(backend, container_name)
        if info and info.get("running"):
            break
        time.sleep(0.5)
    else:
        logger.error(
            "Container created but did not start",
            extra={
                "session_id": session_id,
                "backend": backend,
                "image": image,
                "container_name": container_name,
                "container_id": container_id,
            },
        )
        return SkillResult(
            status="failed",
            content=(f"Container '{container_name}' created but did not start."),
            artifacts={
                "backend": backend,
                "image": image,
                "container_name": container_name,
                "container_id": container_id,
            },
        )

    output = {
        "backend": backend,
        "image": image,
        "container_name": container_name,
        "container_id": container_id,
        "workdir": "/workspace",
    }

    ctx.database.write_memory(session_id, f"container.{container_name}", output)
    logger.info(
        "Container created",
        extra={
            "session_id": session_id,
            "backend": backend,
            "container_name": container_name,
            "container_id": container_id,
        },
    )

    return SkillResult(
        status="success",
        content=json.dumps(output, indent=2, sort_keys=True),
        artifacts=output,
    )


def _validate_inputs(image: str, backend: str | None) -> str:
    """Return an error message if inputs are invalid, or empty string if ok."""
    if not image:
        return (
            "No container image specified. Provide an 'image' argument "
            "or set runtime.default_container_image in harness.yaml."
        )
    if backend is None:
        available = [b for b in BACKENDS if shutil.which(b)]
        return (
            "No container runtime found. "
            f"Tried: {', '.join(BACKENDS)}. "
            f"Available on PATH: {', '.join(available) if available else 'none'}."
        )
    return ""


def _resolve_backend() -> str | None:
    for backend in BACKENDS:
        if shutil.which(backend):
            return backend
    return None


def _inspect_container(backend: str, container_name: str) -> dict[str, Any] | None:
    """Check if a container exists and return its info, or None."""
    try:
        result = subprocess.run(  # noqa: S603
            [backend, "inspect", container_name],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None

    if result.returncode != 0:
        return None

    try:
        inspect_data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None

    if not isinstance(inspect_data, list) or not inspect_data:
        return None

    container = inspect_data[0]
    state = container.get("State", {})
    return {
        "backend": backend,
        "container_name": container_name,
        "container_id": str(container.get("Id", "")),
        "image": str(container.get("Config", {}).get("Image", "")),
        "status": str(state.get("Status", "")),
        "running": bool(state.get("Running", False)),
        "workdir": str(container.get("Config", {}).get("WorkingDir", "/workspace")),
    }
