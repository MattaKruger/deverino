from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import TYPE_CHECKING, Any, TypeVar, overload

from harness_poc.core.events import BaseEvent

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable, Generator

    from harness_poc.core.event_store import EventStore

logger = logging.getLogger(__name__)

E = TypeVar("E", bound=BaseEvent)


class _Published:
    def __await__(self) -> Generator[None, None, None]:
        if False:
            yield None
        return None


class EventBus:
    def __init__(self, event_store: EventStore) -> None:
        self._store: EventStore = event_store
        self._queue: asyncio.Queue[BaseEvent] = asyncio.Queue()
        self._handlers: dict[str, list[Callable[[Any], None]]] = defaultdict(
            list
        )
        self._async_subscribers: list[asyncio.Queue[BaseEvent]] = []

    def publish(self, event: BaseEvent) -> _Published:
        self._store.persist(event)
        self._dispatch(event)
        return _Published()

    async def publish_async(self, event: BaseEvent) -> None:
        await self._store.persist_async(event)
        self._dispatch(event)

    @overload
    def subscribe(
        self, event_type: type[E], handler: Callable[[E], None]
    ) -> None: ...

    @overload
    def subscribe(self, session_id: str) -> AsyncGenerator[BaseEvent, None]: ...

    def subscribe(
        self,
        event_type_or_session_id: type[E] | str,
        handler: Callable[[E], None] | None = None,
    ) -> AsyncGenerator[BaseEvent, None] | None:
        if handler is not None:
            if isinstance(event_type_or_session_id, str):
                msg = "Handler EventBus subscription requires an event type"
                raise TypeError(msg)
            self._handlers[event_type_or_session_id.__name__].append(handler)  # type: ignore[arg-type]
            return None

        if not isinstance(event_type_or_session_id, str):
            msg = "Async EventBus subscription requires a session_id string"
            raise TypeError(msg)

        return self._subscribe_session(event_type_or_session_id)

    def subscribe_session(
        self, session_id: str
    ) -> AsyncGenerator[BaseEvent, None]:
        return self._subscribe_session(session_id)

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
        self._queue.put_nowait(event)
        for subscriber in list(self._async_subscribers):
            subscriber.put_nowait(event)

        for handler in list(self._handlers.get(event.event_type, [])):
            try:
                handler(event)
            except Exception:
                logger.exception(
                    "Event handler raised for %s", event.event_type
                )

    async def _subscribe_session(
        self,
        session_id: str,
    ) -> AsyncGenerator[BaseEvent, None]:
        queue: asyncio.Queue[BaseEvent] = asyncio.Queue()
        self._async_subscribers.append(queue)
        try:
            while True:
                event = await queue.get()
                if event.session_id == session_id:
                    yield event
        finally:
            self._async_subscribers.remove(queue)
