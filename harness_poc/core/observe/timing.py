"""Timing context manager for structured duration logging.

Usage::

    from harness_poc.core.observe import timed, current_trace

    with timed("distiller_llm_call", logger=logger):
        result = await agent.run(prompt)
        # logs "distiller_llm_call completed in 5.23s" on exit
"""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Generator


@contextmanager
def timed(
    operation: str,
    *,
    logger: logging.Logger,
    extra: dict | None = None,
    level: int = logging.DEBUG,
) -> Generator[None]:
    """Log the elapsed time of the wrapped block.

    Args:
        operation: Human-readable operation name (e.g. ``"distiller_llm_call"``).
        logger: Logger to emit the timing message to.
        extra: Optional ``extra`` dict for structured logging
            (typically ``current_trace().as_extra()``).
        level: Log level for the timing message (default ``DEBUG``).
    """
    t0 = time.monotonic()
    try:
        yield
    finally:
        elapsed = time.monotonic() - t0
        logger.log(level, "%s completed in %.3fs", operation, elapsed, extra=extra)
