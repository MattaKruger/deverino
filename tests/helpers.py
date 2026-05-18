from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

from harness_poc.core.events import BaseEvent

if TYPE_CHECKING:
    from collections.abc import Callable

E = TypeVar("E", bound=BaseEvent)


class RecordingEventBus:
    """In-memory EventBus for tests — no persistence, no subscribers."""

    def __init__(self) -> None:
        self.events: list[BaseEvent] = []

    def publish(self, event: BaseEvent) -> None:
        self.events.append(event)

    def subscribe(self, event_type: type[E], handler: Callable[[E], None]) -> None:
        pass

    def get_recent_events(
        self,
        session_id: str,
        limit: int = 20,
        event_types: list[type[BaseEvent]] | None = None,
    ) -> list[BaseEvent]:
        filtered = [e for e in self.events if e.session_id == session_id]
        if event_types is not None:
            names = {t.__name__ for t in event_types}
            filtered = [e for e in filtered if type(e).__name__ in names]
        return filtered[-limit:]
