"""Observability layer — structured tracing, console-to-log bridging, and timing.

Provides three lightweight primitives that hook into the existing logging
infrastructure without new dependencies:

- ``TraceContext`` — correlation IDs propagated through the call stack via
  ``contextvars.ContextVar``.  Every log line from a single user turn shares
  the same ``trace_id``.
- ``LogTap`` — duplicates ``print_text`` / ``print_error`` output to the
  logging system so the REPL's entire interaction surface is replayable
  from the log file.
- ``timed()`` — context manager that logs operation duration on exit.
"""

from harness_poc.core.observe.log_tap import LogTap, get_log_tap
from harness_poc.core.observe.timing import timed
from harness_poc.core.observe.trace import TraceContext, current_trace, new_trace

__all__ = [
    "LogTap",
    "TraceContext",
    "current_trace",
    "get_log_tap",
    "new_trace",
    "timed",
]
