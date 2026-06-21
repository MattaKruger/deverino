from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

DEFAULT_LOG_LEVEL = "INFO"
LOG_FORMAT = "%(asctime)s %(levelname)-7s [%(name)s] %(message)s"
LOG_DATE_FORMAT = "%H:%M:%S"
LOG_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
LOG_BACKUP_COUNT = 5


def configure_logging(
    project_root: Path | None = None,
    *,
    force: bool = False,
) -> Path:
    """Configure harness logging with rotation and return the active log path.

    Logs rotate at 10 MB (configurable via ``HARNESS_LOG_MAX_MB``) with 5
    backups kept (configurable via ``HARNESS_LOG_BACKUPS``).
    """
    log_path = _resolve_log_path(project_root)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger()
    if root_logger.handlers and not force:
        return log_path

    level_name = os.getenv("HARNESS_LOG_LEVEL", DEFAULT_LOG_LEVEL).upper()
    level = getattr(logging, level_name, logging.INFO)

    max_bytes = _env_int("HARNESS_LOG_MAX_MB", LOG_MAX_BYTES // (1024 * 1024)) * 1024 * 1024
    backup_count = _env_int("HARNESS_LOG_BACKUPS", LOG_BACKUP_COUNT)

    handlers: list[logging.Handler] = [
        RotatingFileHandler(
            log_path,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        ),
    ]
    if _truthy_env("HARNESS_LOG_STDERR"):
        handlers.append(logging.StreamHandler())

    logging.basicConfig(
        level=level,
        format=LOG_FORMAT,
        datefmt=LOG_DATE_FORMAT,
        handlers=handlers,
        force=force,
    )

    logging.getLogger(__name__).debug(
        "Logging configured (max %d MB, %d backups)",
        max_bytes // (1024 * 1024),
        backup_count,
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


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default
