from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

if TYPE_CHECKING:
    from collections.abc import Callable

EXPECTED_CALL_COUNT = 2

Flusher = "Callable[[str], None]"


def _make_throttled_flusher(
    flush_fn: Callable[[str], None], interval: float = 0.033
) -> Callable[[str], None]:
    """Mirrors the throttle logic from tui.py on_text_chunk."""
    last_flush: list[float] = [0.0]
    lock = threading.Lock()

    def maybe_flush(text: str) -> None:
        now = time.monotonic()
        with lock:
            if now - last_flush[0] >= interval:
                last_flush[0] = now
                flush_fn(text)

    return maybe_flush


def test_throttle_suppresses_rapid_calls() -> None:
    flush = MagicMock()
    throttled = _make_throttled_flusher(flush, interval=0.1)

    throttled("a")  # first call — fires immediately (last_flush starts at 0.0)
    throttled("b")  # within 100ms — suppressed
    throttled("c")  # within 100ms — suppressed

    assert flush.call_count == 1


def test_throttle_fires_after_interval() -> None:
    flush = MagicMock()
    throttled = _make_throttled_flusher(flush, interval=0.05)

    throttled("a")
    time.sleep(0.06)
    throttled("b")  # after interval — fires again

    assert flush.call_count == EXPECTED_CALL_COUNT
