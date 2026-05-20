from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from sqlmodel import Session, select

if TYPE_CHECKING:
    from sqlalchemy import Engine

from harness_poc.core.events import EVENT_REGISTRY, BaseEvent
from harness_poc.core.models import DbStateEvent

logger = logging.getLogger(__name__)


class EventStore:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @property
    def engine(self) -> Engine:
        return self._engine

    def persist(self, event: BaseEvent) -> None:
        payload = {
            "event_type": event.event_type,
            "payload": event.model_dump(mode="json"),
        }
        with Session(self._engine) as session:
            row = DbStateEvent(
                scope="session",
                scope_id=event.session_id,
                event_type=event.event_type,
                payload=payload,
                created_at=event.created_at.isoformat(timespec="seconds"),
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            event.id = row.id or 0

    async def persist_async(self, event: BaseEvent) -> None:
        await asyncio.to_thread(self.persist, event)

    def get_recent_events(
        self,
        session_id: str,
        limit: int = 20,
        event_types: list[type[BaseEvent]] | None = None,
    ) -> list[BaseEvent]:
        type_names = [t.__name__ for t in event_types] if event_types is not None else None
        with Session(self._engine) as session:
            stmt = (
                select(DbStateEvent)
                .where(DbStateEvent.scope == "session")
                .where(DbStateEvent.scope_id == session_id)
            )
            if type_names:
                stmt = stmt.where(DbStateEvent.event_type.in_(type_names))
            stmt = stmt.order_by(DbStateEvent.id.desc()).limit(limit)  # type: ignore[arg-type]
            rows = session.exec(stmt).all()

        events: list[BaseEvent] = []
        for row in rows:
            try:
                outer = row.payload
                event_type_name = str(outer.get("event_type", ""))
                event_cls = EVENT_REGISTRY.get(event_type_name)
                if event_cls is None:
                    logger.warning("Unknown event_type in store, skipping: %s", event_type_name)
                    continue
                evt = event_cls.model_validate(outer["payload"])
                evt.id = row.id or 0
                events.append(evt)
            except (ValueError, KeyError):
                logger.warning("Skipping malformed event row", exc_info=True)

        events.reverse()
        return events
