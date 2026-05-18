from __future__ import annotations

import logging
import os
from pathlib import Path

DEFAULT_LOG_LEVEL = "INFO"
LOG_FORMAT = (
    "%(asctime)s %(levelname)s [%(name)s] "
    "%(filename)s:%(lineno)d %(message)s"
)


def configure_logging(
    project_root: Path | None = None,
    *,
    force: bool = False,
) -> Path:
    """Configure harness logging and return the active log path."""
    log_path = _resolve_log_path(project_root)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger()
    if root_logger.handlers and not force:
        return log_path

    level_name = os.getenv("HARNESS_LOG_LEVEL", DEFAULT_LOG_LEVEL).upper()
    level = getattr(logging, level_name, logging.INFO)

    handlers: list[logging.Handler] = [
        logging.FileHandler(log_path, encoding="utf-8"),
    ]
    if _truthy_env("HARNESS_LOG_STDERR"):
        handlers.append(logging.StreamHandler())

    logging.basicConfig(
        level=level,
        format=LOG_FORMAT,
        handlers=handlers,
        force=force,
    )

    logging.getLogger(__name__).debug(
        "Logging configured",
        extra={"log_path": str(log_path), "level": level_name},
    )
    return log_path


def get_log_path(project_root: Path | None = None) -> Path:
    return _resolve_log_path(project_root)


def _resolve_log_path(project_root: Path | None) -> Path:
    env_path = os.getenv("HARNESS_LOG_FILE")
    if env_path:
        return Path(env_path).expanduser()

    root = project_root or Path.cwd()
    return root / ".harness" / "logs" / "harness.log"


def _truthy_env(name: str) -> bool:
    value = os.getenv(name, "").strip().lower()
    return value in {"1", "true", "yes", "on"}
