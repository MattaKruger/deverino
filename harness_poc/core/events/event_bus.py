from __future__ import annotations

import asyncio
import contextlib
import logging
from collections import defaultdict
from typing import TYPE_CHECKING, Any, TypeVar

from harness_poc.core.events.events import BaseEvent
from harness_poc.core.observe import current_trace

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable

    from harness_poc.core.events.event_store import EventStore

logger = logging.getLogger(__name__)

E = TypeVar("E", bound=BaseEvent)


class EventBus:
    def __init__(self, event_store: EventStore) -> None:
        self._store: EventStore = event_store
        self._handlers: dict[str, list[Callable[[Any], None]]] = defaultdict(list)
        self._async_subscribers: list[asyncio.Queue[BaseEvent]] = []

    def publish(self, event: BaseEvent) -> None:
        self._store.persist(event)
        self._dispatch(event)
        trace = current_trace()
        handlers = self._handlers.get(event.event_type, [])
        logger.debug(
            "Published event: %s (handlers=%d)",
            type(event).__name__,
            len(handlers),
            extra=trace.as_extra() if trace else None,
        )

    async def publish_async(self, event: BaseEvent) -> None:
        await self._store.persist_async(event)
        self._dispatch(event)

    def subscribe(self, event_type: type[E], handler: Callable[[E], None]) -> None:
        if not isinstance(event_type, type):
            msg = "subscribe() requires an event type as first argument; use subscribe_session() for async session subscriptions"
            raise TypeError(msg)
        self._handlers[event_type.__name__].append(handler)  # type: ignore[arg-type]

    def unsubscribe(self, event_type: type[E], handler: Callable[[E], None]) -> None:
        with contextlib.suppress(ValueError):
            self._handlers[event_type.__name__].remove(handler)  # type: ignore[arg-type]

    async def subscribe_session(self, session_id: str) -> AsyncGenerator[BaseEvent]:
        # ponytail: maxsize caps memory per slow subscriber; QueueFull drops with warning
        queue: asyncio.Queue[BaseEvent] = asyncio.Queue(maxsize=500)
        self._async_subscribers.append(queue)
        try:
            while True:
                event = await queue.get()
                if event.session_id == session_id:
                    yield event
        finally:
            with contextlib.suppress(ValueError):
                self._async_subscribers.remove(queue)

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

    def _dispatch(self, event: BaseEvent) -> None:
        for subscriber in list(self._async_subscribers):
            try:
                subscriber.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning(
                    "Subscriber queue full, dropping event: %s", type(event).__name__
                )

        for handler in list(self._handlers.get(event.event_type, [])):
            try:
                handler(event)
            except Exception:
                logger.exception("Event handler raised for %s", event.event_type)
