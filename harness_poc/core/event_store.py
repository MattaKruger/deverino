from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

from harness_poc.core.events import EVENT_REGISTRY, BaseEvent

logger = logging.getLogger(__name__)


class EventStore:
    def __init__(self, database_path: Path | str) -> None:
        self.database_path = Path(database_path)

    def persist(self, event: BaseEvent) -> None:
        payload = json.dumps(
            {
                "event_type": event.event_type,
                "payload": event.model_dump(mode="json"),
            },
            sort_keys=True,
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO state_events (scope, scope_id, event_type, payload, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    "session",
                    event.session_id,
                    event.event_type,
                    payload,
                    event.created_at.isoformat(timespec="seconds"),
                ),
            )

    def get_recent_events(
        self,
        session_id: str,
        limit: int = 20,
        event_types: list[type[BaseEvent]] | None = None,
    ) -> list[BaseEvent]:
        type_names = (
            [t.__name__ for t in event_types]
            if event_types is not None
            else None
        )
        with self._connect() as conn:
            if type_names:
                placeholders = ",".join("?" * len(type_names))
                cursor = conn.execute(
                    f"""
                    SELECT payload FROM state_events
                    WHERE scope = 'session'
                      AND scope_id = ?
                      AND event_type IN ({placeholders})
                    ORDER BY id DESC
                    LIMIT ?
                    """,  # noqa: S608
                    (session_id, *type_names, limit),
                )
            else:
                cursor = conn.execute(
                    """
                    SELECT payload FROM state_events
                    WHERE scope = 'session'
                      AND scope_id = ?
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (session_id, limit),
                )
            rows = cursor.fetchall()

        events: list[BaseEvent] = []
        for row in rows:
            try:
                outer = json.loads(str(row["payload"]))
                event_type_name = outer.get("event_type", "")
                event_cls = EVENT_REGISTRY.get(event_type_name)
                if event_cls is None:
                    logger.warning(
                        "Unknown event_type in store, skipping: %s",
                        event_type_name,
                    )
                    continue
                events.append(event_cls.model_validate(outer["payload"]))
            except (json.JSONDecodeError, ValueError, KeyError):
                logger.warning("Skipping malformed event row", exc_info=True)

        events.reverse()
        return events

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.database_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        return conn
