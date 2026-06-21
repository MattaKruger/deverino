"""LogTap — bridges Rich console output into the Python logging system.

When enabled, every ``print_text``, ``print_error``, and ``print_markdown``
call is duplicated to the ``harness_poc.repl.console`` logger.  This means
the entire REPL interaction surface — user inputs, agent responses, workflow
results, error messages — is replayable from the log file.

Usage::

    from harness_poc.core.observe import get_log_tap
    tap = get_log_tap()
    tap.enabled = True
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_LOG_TAP: LogTap | None = None


class LogTap:
    """Singleton that duplicates console output to the logging system."""

    enabled: bool = False

    def on_print_text(self, text: str, *, markup: bool = True) -> None:  # noqa: ARG002
        """Called by ``print_text``.  Status/UI messages logged at DEBUG."""
        if self.enabled:
            _console_logger().debug("%s", text.strip())

    def on_print_error(self, message: str) -> None:
        """Called by ``print_error``.  Errors logged at ERROR."""
        if self.enabled:
            _console_logger().error("%s", message.strip())

    def on_print_markdown(self, markdown: str) -> None:
        """Called by ``print_markdown``.  Agent responses logged at INFO."""
        if self.enabled:
            _console_logger().info("%s", markdown.strip())


def get_log_tap() -> LogTap:
    """Return the process-wide singleton LogTap, creating it on first call."""
    global _LOG_TAP  # noqa: PLW0603
    if _LOG_TAP is None:
        _LOG_TAP = LogTap()
    return _LOG_TAP


def _console_logger() -> logging.Logger:
    return logging.getLogger("harness_poc.repl.console")
