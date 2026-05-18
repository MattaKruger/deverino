from __future__ import annotations

import logging
from collections import defaultdict
from typing import TYPE_CHECKING, Any, TypeVar

from harness_poc.core.events import BaseEvent

if TYPE_CHECKING:
    from collections.abc import Callable

    from harness_poc.core.event_store import EventStore

logger = logging.getLogger(__name__)

E = TypeVar("E", bound=BaseEvent)


class EventBus:
    def __init__(self, event_store: EventStore) -> None:
        self._store: EventStore = event_store
        self._handlers: dict[str, list[Callable[[Any], None]]] = defaultdict(list)

    def publish(self, event: BaseEvent) -> None:
        self._store.persist(event)
        for handler in list(self._handlers.get(event.event_type, [])):
            try:
                handler(event)
            except Exception:
                logger.exception("Event handler raised for %s", event.event_type)

    def subscribe(self, event_type: type[E], handler: Callable[[E], None]) -> None:
        self._handlers[event_type.__name__].append(handler)  # type: ignore[arg-type]

    def get_recent_events(
        self,
        session_id: str,
        limit: int = 20,
        event_types: list[type[BaseEvent]] | None = None,
    ) -> list[BaseEvent]:
        return self._store.get_recent_events(
            session_id=session_id,
            limit=limit,
            event_types=event_types,
        )
