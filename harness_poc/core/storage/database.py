from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import inspect, text
from sqlmodel import Session, col, select

from harness_poc.core.observe import current_trace, timed

if TYPE_CHECKING:
    from sqlalchemy import Engine

    from harness_poc.core.events import ContextMapEvent
    from harness_poc.core.storage.state import StateSection

from harness_poc.core.context_map.schema import MapEntry
from harness_poc.core.storage.db_engine import create_db_engine
from harness_poc.core.storage.models import (
    DbContextMap,
    DbContextMapCycle,
    DbContextMapEvent,
    DbDocumentChunk,
    DbDocumentSource,
    DbMaterializedContextMap,
    DbProjectState,
    DbSession,
    DbSessionMessage,
    DbSessionState,
    DbSharedMemory,
    DbStateEvent,
    DbStateProposal,
    SQLModel,
)
from harness_poc.core.storage.state import StatePayload, StateProposal

logger = logging.getLogger(__name__)


class BlackboardDatabase:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @classmethod
    def from_url(cls, database_url: str) -> BlackboardDatabase:
        engine = create_db_engine(database_url)
        db = cls(engine)
        db.create_tables()
        return db

    @property
    def engine(self) -> Engine:
        return self._engine

    def create_tables(self) -> None:
        SQLModel.metadata.create_all(self._engine)
        self._ensure_context_map_freeze_column()
        self._ensure_context_map_schema_version_column()
        self._ensure_context_map_cycles_table()
        self._ensure_sessions_active_corpus_column()
        self.copt_ensure_schema()

    def wipe_tables(self) -> None:
        """Drop all tables (including orphans) and recreate from metadata."""
        SQLModel.metadata.drop_all(self._engine)
        # Orphaned tables no longer in metadata (e.g. after model deletion)
        with Session(self._engine) as s:
            s.exec(text("DROP TABLE IF EXISTS context_events_v2 CASCADE"))  # type: ignore[arg-type]
            s.commit()
        self.create_tables()

    def start_session(
        self,
        objective: str,
        *,
        active_corpus_key: str | None = None,
    ) -> str:
        trace = current_trace()
        extra = trace.as_extra() if trace else None
        with timed("db:start_session", logger=logger, extra=extra):
            session_id = str(uuid.uuid4())
            with Session(self._engine) as session:
                session.add(
                    DbSession(
                        session_id=session_id,
                        global_objective=objective,
                        status="active",
                        created_at=self._utc_now(),
                        active_corpus_key=active_corpus_key,
                    )
                )
                session.commit()
            return session_id

    def append_session_messages(
        self,
        session_id: str,
        messages_blob: list[dict[str, Any]],
    ) -> int:
        with Session(self._engine) as session:
            next_ordinal = (
                session.exec(
                    select(DbSessionMessage.ordinal)
                    .where(DbSessionMessage.session_id == session_id)
                    .order_by(col(DbSessionMessage.ordinal).desc())
                    .limit(1)
                ).first()
                or 0
            ) + 1
            session.add(
                DbSessionMessage(
                    session_id=session_id,
                    ordinal=next_ordinal,
                    messages_blob=messages_blob,
                    created_at=self._utc_now(),
                )
            )
            session.commit()
            return next_ordinal

    def load_session_messages(self, session_id: str) -> list[dict[str, Any]]:
        with Session(self._engine) as session:
            rows = session.exec(
                select(DbSessionMessage)
                .where(DbSessionMessage.session_id == session_id)
                .order_by(col(DbSessionMessage.ordinal))
            ).all()
        blob: list[dict[str, Any]] = []
        for row in rows:
            blob.extend(row.messages_blob)
        return blob

    def get_last_session_id(self) -> str | None:
        with Session(self._engine) as session:
            return session.exec(
                select(DbSession.session_id).order_by(col(DbSession.created_at).desc()).limit(1)
            ).first()

    def session_exists(self, session_id: str) -> bool:
        with Session(self._engine) as session:
            return session.get(DbSession, session_id) is not None

    def list_recent_sessions(self, limit: int = 20) -> list[dict[str, Any]]:
        """Return the most recent active sessions with message counts."""
        rows = []
        with Session(self._engine) as session:
            result = session.exec(
                text(
                    "SELECT s.session_id, s.global_objective, s.created_at, "
                    "COALESCE("
                    "  (SELECT COUNT(*) FROM session_messages m WHERE m.session_id = s.session_id), 0"
                    ") as message_count "
                    "FROM sessions s "
                    "WHERE s.status = 'active' "
                    "ORDER BY s.created_at DESC "
                    "LIMIT :limit"
                ).bindparams(limit=limit),
            ).all()
            for row in result:
                rows.append(
                    {
                        "session_id": row[0],
                        "objective": row[1],
                        "created_at": row[2],
                        "message_count": row[3],
                    }
                )
        return rows

    def delete_session(self, session_id: str) -> bool:
        """Soft-delete a session by setting its status to 'archived'.

        Returns True if the session was found and archived, False otherwise.
        """
        with Session(self._engine) as session_obj:
            db_session = session_obj.get(DbSession, session_id)
            if db_session is None:
                return False
            db_session.status = "archived"
            session_obj.add(db_session)
            session_obj.commit()
        return True

    def write_memory(self, session_id: str, key: str, payload: str | dict[str, Any]) -> None:
        data_payload = json.dumps(payload, sort_keys=True) if isinstance(payload, dict) else payload
        with Session(self._engine) as session:
            session.add(
                DbSharedMemory(
                    session_id=session_id,
                    memory_key=key,
                    data_payload=data_payload,
                    created_at=self._utc_now(),
                )
            )
            session.commit()

    def read_memory(self, session_id: str, key: str) -> dict[str, Any] | str | None:
        with Session(self._engine) as session:
            row = session.exec(
                select(DbSharedMemory)
                .where(DbSharedMemory.session_id == session_id)
                .where(DbSharedMemory.memory_key == key)
                .order_by(
                    col(DbSharedMemory.created_at).desc(),
                    col(DbSharedMemory.id).desc(),
                )
                .limit(1)
            ).first()
        if row is None:
            return None
        return self._decode_payload(row.data_payload)

    def list_memory_keys(self, session_id: str) -> list[str]:
        with Session(self._engine) as session:
            rows = session.exec(
                select(DbSharedMemory.memory_key)
                .where(DbSharedMemory.session_id == session_id)
                .distinct()
                .order_by(DbSharedMemory.memory_key)
            ).all()
        return list(rows)

    def ensure_project_state(self, project_id: str = "default") -> StatePayload:
        trace = current_trace()
        extra = trace.as_extra() if trace else None
        with timed("db:ensure_project_state", logger=logger, extra=extra):
            payload = self.read_project_state(project_id)
            if payload is not None:
                return payload
            empty_state = StatePayload()
            with Session(self._engine) as session:
                session.add(
                    DbProjectState(
                        project_id=project_id,
                        state_payload=empty_state.to_dict(),
                        version=1,
                        updated_at=self._utc_now(),
                    )
                )
                session.commit()
            return empty_state

    def read_project_state(self, project_id: str = "default") -> StatePayload | None:
        with Session(self._engine) as session:
            row = session.get(DbProjectState, project_id)
        if row is None:
            return None
        return StatePayload.from_dict(row.state_payload)

    def ensure_session_state(self, session_id: str) -> StatePayload:
        trace = current_trace()
        extra = trace.as_extra() if trace else None
        with timed("db:ensure_session_state", logger=logger, extra=extra):
            payload = self.read_session_state(session_id)
            if payload is not None:
                return payload
            empty_state = StatePayload()
            with Session(self._engine) as session:
                session.add(
                    DbSessionState(
                        session_id=session_id,
                        state_payload=empty_state.to_dict(),
                        version=1,
                        dirty=False,
                        updated_at=self._utc_now(),
                    )
                )
                session.commit()
            return empty_state

    def read_session_state(self, session_id: str) -> StatePayload | None:
        with Session(self._engine) as session:
            row = session.get(DbSessionState, session_id)
        if row is None:
            return None
        return StatePayload.from_dict(row.state_payload)

    def append_session_state(
        self,
        session_id: str,
        section: StateSection,
        text: str,
    ) -> StatePayload:
        current_state = self.ensure_session_state(session_id)
        next_state = current_state.append(section, text)
        now = self._utc_now()
        with Session(self._engine) as session:
            row = session.get(DbSessionState, session_id)
            if row is not None:
                row.state_payload = next_state.to_dict()
                row.version += 1
                row.dirty = True
                row.updated_at = now
            session.add(
                DbStateEvent(
                    scope="session",
                    scope_id=session_id,
                    event_type=f"append_{section}",
                    payload={
                        "event_type": f"append_{section}",
                        "payload": {"text": text},
                    },
                    created_at=now,
                )
            )
            session.commit()
        return next_state

    def create_state_proposal(self, session_id: str) -> StateProposal:
        trace = current_trace()
        extra = trace.as_extra() if trace else None
        with timed("db:create_state_proposal", logger=logger, extra=extra):
            session_state = self.ensure_session_state(session_id)
            if session_state.is_empty():
                msg = "Session state is empty; nothing to propose"
                logger.warning("%s session_id=%s", msg, session_id, extra=extra)
                raise ValueError(msg)
            proposal = StateProposal.create(session_id=session_id, payload=session_state)
            now = self._utc_now()
            with Session(self._engine) as session:
                session.add(
                    DbStateProposal(
                        proposal_id=proposal.proposal_id,
                        session_id=proposal.session_id,
                        status=proposal.status,
                        proposal_payload=proposal.payload.to_dict(),
                        created_at=now,
                        resolved_at=None,
                    )
                )
                session.add(
                    DbStateEvent(
                        scope="session",
                        scope_id=session_id,
                        event_type="proposal_created",
                        payload={
                            "event_type": "proposal_created",
                            "payload": {"proposal_id": proposal.proposal_id},
                        },
                        created_at=now,
                    )
                )
                session.commit()
            return proposal

    def read_state_proposal(self, proposal_id: str) -> StateProposal | None:
        with Session(self._engine) as session:
            row = session.get(DbStateProposal, proposal_id)
        if row is None:
            return None
        return StateProposal.from_row_payload(
            proposal_id=row.proposal_id,
            session_id=row.session_id,
            status=row.status,
            proposal_payload=json.dumps(row.proposal_payload),
        )

    def approve_state_proposal(
        self,
        proposal_id: str,
        project_id: str = "default",
    ) -> StatePayload:
        trace = current_trace()
        extra = trace.as_extra() if trace else None
        with timed("db:approve_state_proposal", logger=logger, extra=extra):
            now = self._utc_now()
            with Session(self._engine) as session:
                proposal_row = session.get(DbStateProposal, proposal_id)
                if proposal_row is None:
                    msg = f"State proposal not found: {proposal_id}"
                    logger.error("%s", msg, extra=extra)
                    raise ValueError(msg)
                if proposal_row.status != "pending":
                    msg = f"State proposal is not pending: {proposal_id}"
                    logger.error("%s", msg, extra=extra)
                    raise ValueError(msg)

                proposal_payload = StatePayload.from_dict(proposal_row.proposal_payload)

                project_row = session.get(DbProjectState, project_id)
                if project_row is None:
                    project_row = DbProjectState(
                        project_id=project_id,
                        state_payload=StatePayload().to_dict(),
                        version=0,
                        updated_at=now,
                    )
                    session.add(project_row)
                    session.flush()

                next_state = StatePayload.from_dict(project_row.state_payload).append_payload(
                    proposal_payload
                )
                project_row.state_payload = next_state.to_dict()
                project_row.version += 1
                project_row.updated_at = now

                proposal_row.status = "approved"
                proposal_row.resolved_at = now

                session_state_row = session.get(DbSessionState, proposal_row.session_id)
                if session_state_row is not None:
                    session_state_row.dirty = False
                    session_state_row.updated_at = now

                session.add(
                    DbStateEvent(
                        scope="project",
                        scope_id=project_id,
                        event_type="proposal_approved",
                        payload={
                            "event_type": "proposal_approved",
                            "payload": {
                                "proposal_id": proposal_id,
                                "session_id": proposal_row.session_id,
                            },
                        },
                        created_at=now,
                    )
                )
                session.commit()

            return next_state

    def list_pending_proposals(self) -> list[dict[str, Any]]:
        """Return all pending state proposals as dicts."""
        with Session(self._engine) as session:
            rows = session.exec(
                select(DbStateProposal)
                .where(DbStateProposal.status == "pending")
                .order_by(col(DbStateProposal.created_at).desc())
            ).all()
        return [
            {
                "proposal_id": row.proposal_id,
                "session_id": row.session_id,
                "status": row.status,
                "payload": StatePayload.from_dict(row.proposal_payload).to_dict(),
                "created_at": row.created_at,
            }
            for row in rows
        ]

    def approve_latest_proposal(self, project_id: str = "default") -> StatePayload:
        with Session(self._engine) as session:
            row = session.exec(
                select(DbStateProposal)
                .where(DbStateProposal.status == "pending")
                .order_by(col(DbStateProposal.created_at).desc())
                .limit(1)
            ).first()
        if row is None:
            msg = "No pending state proposals found"
            raise ValueError(msg)
        return self.approve_state_proposal(
            proposal_id=row.proposal_id,
            project_id=project_id,
        )

    def reject_state_proposal(self, proposal_id: str) -> None:
        trace = current_trace()
        extra = trace.as_extra() if trace else None
        with timed("db:reject_state_proposal", logger=logger, extra=extra):
            now = self._utc_now()
            with Session(self._engine) as session:
                proposal_row = session.get(DbStateProposal, proposal_id)
                if proposal_row is None:
                    msg = f"State proposal not found: {proposal_id}"
                    logger.error("%s", msg, extra=extra)
                    raise ValueError(msg)
                if proposal_row.status != "pending":
                    msg = f"State proposal is not pending: {proposal_id}"
                    logger.error("%s", msg, extra=extra)
                    raise ValueError(msg)
                proposal_row.status = "rejected"
                proposal_row.resolved_at = now
                session.add(
                    DbStateEvent(
                        scope="session",
                        scope_id=proposal_row.session_id,
                        event_type="proposal_rejected",
                        payload={
                            "event_type": "proposal_rejected",
                            "payload": {"proposal_id": proposal_id},
                        },
                        created_at=now,
                    )
                )
                session.commit()

    # ── Phase 2: facts + events ──

    def set_project_fact(self, key: str, value: str, project_id: str = "default") -> StatePayload:
        """Set a key-value fact directly on project state (no proposal needed)."""
        current = self.ensure_project_state(project_id)
        next_state = current.set_fact(key, value)
        now = self._utc_now()
        with Session(self._engine) as session:
            row = session.get(DbProjectState, project_id)
            if row is not None:
                row.state_payload = next_state.to_dict()
                row.version += 1
                row.updated_at = now
            session.add(
                DbStateEvent(
                    scope="project",
                    scope_id=project_id,
                    event_type="fact_set",
                    payload={
                        "event_type": "fact_set",
                        "payload": {"key": key, "value": value},
                    },
                    created_at=now,
                )
            )
            session.commit()
        return next_state

    def get_project_fact(self, key: str, project_id: str = "default") -> str | None:
        """Read a single fact from project state."""
        state = self.ensure_project_state(project_id)
        return state.facts.get(key)

    def is_session_state_dirty(self, session_id: str) -> bool:
        """Check whether session state has unconsolidated changes."""
        with Session(self._engine) as session:
            row = session.get(DbSessionState, session_id)
        return row.dirty if row is not None else False

    def list_state_events(
        self,
        *,
        session_id: str | None = None,
        limit: int = 50,
        event_types: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Return recent state_events, optionally filtered by scope and type."""
        with Session(self._engine) as session:
            stmt = select(DbStateEvent).order_by(col(DbStateEvent.id).desc()).limit(limit)
            if session_id is not None:
                stmt = stmt.where(DbStateEvent.scope_id == session_id)
            if event_types:
                stmt = stmt.where(col(DbStateEvent.event_type).in_(event_types))
            rows = session.exec(stmt).all()
        return [
            {
                "id": row.id,
                "scope": row.scope,
                "scope_id": row.scope_id,
                "event_type": row.event_type,
                "payload": row.payload,
                "created_at": row.created_at,
            }
            for row in rows
        ]

    def upsert_document_source(self, source: DbDocumentSource) -> None:
        if self._engine.dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import insert
        else:
            from sqlalchemy.dialects.sqlite import insert

        stmt = insert(DbDocumentSource).values(
            source_id=source.source_id,
            uri=source.uri,
            title=source.title,
            kind=source.kind,
            content_hash=source.content_hash,
            status=source.status,
            chunk_count=source.chunk_count,
            indexed_at=source.indexed_at,
            error=source.error,
            metadata_payload=source.metadata_payload,
            updated_at=source.updated_at,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["source_id"],
            set_={
                "uri": source.uri,
                "title": source.title,
                "kind": source.kind,
                "content_hash": source.content_hash,
                "status": source.status,
                "chunk_count": source.chunk_count,
                "indexed_at": source.indexed_at,
                "error": source.error,
                "metadata_payload": source.metadata_payload,
                "updated_at": source.updated_at,
            },
        )
        with self._engine.connect() as conn:
            conn.execute(stmt)
            conn.commit()

    def get_document_source(self, source_id: str) -> DbDocumentSource | None:
        with Session(self._engine) as session:
            return session.get(DbDocumentSource, source_id)

    def list_document_sources(self) -> list[DbDocumentSource]:
        with Session(self._engine) as session:
            return list(session.exec(select(DbDocumentSource)).all())

    def upsert_document_chunk(self, chunk: DbDocumentChunk) -> None:
        if self._engine.dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import insert
        else:
            from sqlalchemy.dialects.sqlite import insert

        stmt = insert(DbDocumentChunk).values(
            chunk_id=chunk.chunk_id,
            source_id=chunk.source_id,
            chunk_index=chunk.chunk_index,
            content_hash=chunk.content_hash,
            vespa_id=chunk.vespa_id,
            indexed_at=chunk.indexed_at,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["chunk_id"],
            set_={
                "source_id": chunk.source_id,
                "chunk_index": chunk.chunk_index,
                "content_hash": chunk.content_hash,
                "vespa_id": chunk.vespa_id,
                "indexed_at": chunk.indexed_at,
            },
        )
        with self._engine.connect() as conn:
            conn.execute(stmt)
            conn.commit()

    def list_chunks_for_source(self, source_id: str) -> list[DbDocumentChunk]:
        with Session(self._engine) as session:
            return list(
                session.exec(
                    select(DbDocumentChunk).where(DbDocumentChunk.source_id == source_id)
                ).all()
            )

    def append_context_map_event(self, event: ContextMapEvent) -> None:
        trace = current_trace()
        extra = trace.as_extra() if trace else None
        with (
            timed("db:append_context_map_event", logger=logger, extra=extra),
            Session(self._engine) as session,
        ):
            session.add(
                DbContextMapEvent(
                    event_id=event.event_id,
                    corpus_key=event.corpus_key,
                    session_id=event.session_id,
                    event_type=event.event_type,
                    payload=event.model_dump_json(),
                    timestamp=event.timestamp,
                    processed=0,
                )
            )
            session.commit()

    def get_pending_context_map_events(
        self, corpus_key: str, limit: int = 50
    ) -> list[DbContextMapEvent]:
        with Session(self._engine) as session:
            return list(
                session.exec(
                    select(DbContextMapEvent)
                    .where(DbContextMapEvent.corpus_key == corpus_key)
                    .where(DbContextMapEvent.processed == 0)
                    .order_by(DbContextMapEvent.timestamp)
                    .limit(limit)
                ).all()
            )

    def get_pending_corpus_keys(self) -> list[str]:
        with Session(self._engine) as session:
            rows = session.exec(
                select(DbContextMapEvent.corpus_key)
                .where(DbContextMapEvent.processed == 0)
                .distinct()
            ).all()
        return list(rows)

    def get_all_corpus_keys(self) -> list[str]:
        """Return every known corpus key — materialized or pending.

        Union of (a) corpora with a materialized context map and (b) corpora
        that still have unprocessed events queued. Sorted lexicographically so
        callers get a stable order without re-sorting.
        """
        with Session(self._engine) as session:
            materialized = session.exec(select(DbContextMap.corpus_key)).all()
            pending = session.exec(
                select(DbContextMapEvent.corpus_key)
                .where(DbContextMapEvent.processed == 0)
                .distinct()
            ).all()
        return sorted(set(materialized) | set(pending))

    def get_session_corpus_key(
        self,
        session_id: str,
        *,
        default: str,
    ) -> str:
        """Return the stored active_corpus_key, falling back to `default`.

        Default applies to legacy sessions created before the schema change
        and to fresh sessions started without an explicit --corpus flag.
        """
        with Session(self._engine) as session:
            row = session.get(DbSession, session_id)
        if row is None or not row.active_corpus_key:
            return default
        return row.active_corpus_key

    def get_context_map(self, corpus_key: str) -> list[MapEntry] | None:
        with Session(self._engine) as session:
            row = session.get(DbContextMap, corpus_key)
        if row is None:
            return None
        try:
            raw = json.loads(row.map_json)
        except json.JSONDecodeError:
            return None
        return [MapEntry.model_validate(e) for e in raw] if isinstance(raw, list) else []

    def is_map_frozen(self, corpus_key: str, now: str | None = None) -> bool:
        if now is None:
            now = self._utc_now()
        with Session(self._engine) as session:
            row = session.get(DbContextMap, corpus_key)
        if row is None or row.freeze_until is None:
            return False
        return row.freeze_until > now

    def set_map_freeze(self, corpus_key: str, freeze_until: str) -> None:
        with Session(self._engine) as session:
            row = session.get(DbContextMap, corpus_key)
            if row is not None:
                row.freeze_until = freeze_until
                session.add(row)
                session.commit()

    def write_map_and_mark_processed(
        self,
        corpus_key: str,
        map_entries: list[MapEntry],
        token_count: int,
        event_ids: list[str],
        freeze_until: str | None = None,
    ) -> None:
        trace = current_trace()
        extra = trace.as_extra() if trace else None
        with timed("db:write_map", logger=logger, extra=extra):
            now = self._utc_now()
            serialized = json.dumps(
                [entry.model_dump(mode="json") for entry in map_entries],
                sort_keys=True,
            )
            with Session(self._engine) as session:
                row = session.get(DbContextMap, corpus_key)
                if row is None:
                    session.add(
                        DbContextMap(
                            corpus_key=corpus_key,
                            map_json=serialized,
                            token_count=token_count,
                            version=1,
                            last_updated=now,
                            freeze_until=freeze_until,
                            schema_version=2,
                        )
                    )
                else:
                    row.map_json = serialized
                    row.token_count = token_count
                    row.version += 1
                    row.last_updated = now
                    row.freeze_until = freeze_until
                    row.schema_version = 2
                    session.add(row)
                for event_id in event_ids:
                    event_row = session.get(DbContextMapEvent, event_id)
                    if event_row is not None:
                        event_row.processed = 1
                        session.add(event_row)
                session.commit()

    def get_and_bump_cycle(self, corpus_key: str) -> int:
        """Atomically increment and return the post-increment cycle_n for a corpus.

        First call for a fresh corpus returns 1.
        Uses INSERT ... ON CONFLICT (Postgres) or SELECT+UPDATE in a transaction (SQLite).
        """
        now = self._utc_now()
        with Session(self._engine) as session:
            row = session.get(DbContextMapCycle, corpus_key)
            if row is None:
                row = DbContextMapCycle(corpus_key=corpus_key, cycle_n=1, updated_at=now)
                session.add(row)
            else:
                row.cycle_n += 1
                row.updated_at = now
                session.add(row)
            session.commit()
            return row.cycle_n

    def get_cycle(self, corpus_key: str) -> int:
        """Read-only cycle_n lookup. Returns 0 if no cycle exists yet."""
        with Session(self._engine) as session:
            row = session.get(DbContextMapCycle, corpus_key)
        return row.cycle_n if row is not None else 0

    def get_cycles(self, corpus_keys: list[str]) -> dict[str, int]:
        """Bulk read-only cycle_n lookup. Keys not found default to 0."""
        if not corpus_keys:
            return {}
        with Session(self._engine) as session:
            rows = session.exec(
                select(DbContextMapCycle).where(col(DbContextMapCycle.corpus_key).in_(corpus_keys))
            ).all()
        return {row.corpus_key: row.cycle_n for row in rows}

    def get_context_maps(self, corpus_keys: list[str]) -> dict[str, list[MapEntry]]:
        """Bulk read context maps for multiple corpora (cross-corpus enrichment)."""
        if not corpus_keys:
            return {}
        with Session(self._engine) as session:
            rows = session.exec(
                select(DbContextMap).where(col(DbContextMap.corpus_key).in_(corpus_keys))
            ).all()
        result: dict[str, list[MapEntry]] = {}
        for row in rows:
            try:
                raw = json.loads(row.map_json)
            except json.JSONDecodeError:
                continue
            if isinstance(raw, list):
                entries = [MapEntry.model_validate(e) for e in raw]
            else:
                continue
            result[row.corpus_key] = entries
        return result

    def _ensure_context_map_schema_version_column(self) -> None:
        inspector = inspect(self._engine)
        if not inspector.has_table("context_map"):
            return
        columns = {column["name"] for column in inspector.get_columns("context_map")}
        if "schema_version" in columns:
            return
        with self._engine.begin() as connection:
            connection.execute(
                text("ALTER TABLE context_map ADD COLUMN schema_version INTEGER DEFAULT 1")
            )

    def _ensure_context_map_cycles_table(self) -> None:
        inspector = inspect(self._engine)
        if inspector.has_table("context_map_cycles"):
            return
        DbContextMapCycle.metadata.create_all(self._engine)

    def _ensure_context_map_freeze_column(self) -> None:
        inspector = inspect(self._engine)
        if not inspector.has_table("context_map"):
            return
        columns = {column["name"] for column in inspector.get_columns("context_map")}
        if "freeze_until" in columns:
            return
        with self._engine.begin() as connection:
            connection.execute(text("ALTER TABLE context_map ADD COLUMN freeze_until TEXT"))

    def _ensure_sessions_active_corpus_column(self) -> None:
        """Add sessions.active_corpus_key for databases predating Gap 2."""
        inspector = inspect(self._engine)
        cols = {c["name"] for c in inspector.get_columns("sessions")}
        if "active_corpus_key" in cols:
            return
        with self._engine.begin() as conn:
            conn.execute(
                text("ALTER TABLE sessions ADD COLUMN active_corpus_key TEXT"),
            )

    # ------------------------------------------------------------------
    # V2 materialized context maps
    # ------------------------------------------------------------------

    def upsert_materialized_context_map(
        self,
        project_id: str,
        active_persona: str,
        pedagogy_snapshot: dict[str, Any],
        verified_state: dict[str, Any],
        last_event_id: str,
    ) -> None:
        """Insert or update a materialized context map snapshot."""
        with Session(self._engine) as session:
            existing = session.get(DbMaterializedContextMap, project_id)
            if existing is not None:
                existing.active_persona = active_persona
                existing.pedagogy_snapshot = pedagogy_snapshot
                existing.verified_state = verified_state
                existing.last_event_id = last_event_id
                existing.updated_at = self._utc_now()
            else:
                session.add(
                    DbMaterializedContextMap(
                        project_id=project_id,
                        active_persona=active_persona,
                        pedagogy_snapshot=pedagogy_snapshot,
                        verified_state=verified_state,
                        last_event_id=last_event_id,
                        updated_at=self._utc_now(),
                    )
                )
            session.commit()

    def get_materialized_context_map(
        self,
        project_id: str,
    ) -> dict[str, Any] | None:
        """Return the latest materialized context map for a project, or None."""
        with Session(self._engine) as session:
            row = session.get(DbMaterializedContextMap, project_id)
            if row is None:
                return None
            return {
                "project_id": row.project_id,
                "active_persona": row.active_persona,
                "pedagogy_snapshot": row.pedagogy_snapshot,
                "verified_state": row.verified_state,
                "last_event_id": row.last_event_id,
                "updated_at": row.updated_at,
            }

    # ------------------------------------------------------------------
    # CopT Gate -- pgvector embedding dedup (plans/09-copt-gate-plan.md)
    # ------------------------------------------------------------------

    _copt_available: bool | None = None

    def copt_is_available(self) -> bool:
        """Return True if the CopT gate can run (pgvector + table exists)."""
        if self._copt_available is not None:
            return self._copt_available
        if self._engine.dialect.name != "postgresql":
            self._copt_available = False
            return False
        # Check if the embeddings table actually exists.
        try:
            with self._engine.connect() as conn:
                row = conn.execute(
                    text(
                        "SELECT EXISTS ("
                        "  SELECT FROM information_schema.tables "
                        "  WHERE table_name = 'context_map_embeddings'"
                        ")"
                    )
                ).scalar()
                self._copt_available = bool(row)
        except Exception:
            self._copt_available = False
        return self._copt_available

    def copt_ensure_schema(self) -> None:
        """Create pgvector extension and embeddings table on PostgreSQL only.

        Gracefully handles PostgreSQL instances without the pgvector extension
        installed. Uses separate transactions for extension creation and table
        creation so a missing extension doesn't abort the table setup.
        """
        if self._engine.dialect.name != "postgresql":
            self._copt_available = False
            return
        import logging

        _log = logging.getLogger(__name__)

        # Attempt extension creation in its own transaction
        try:
            with self._engine.begin() as conn:
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        except Exception:
            _log.warning(
                "pgvector extension not available — CopT gate disabled.",
                exc_info=True,
            )
            self._copt_available = False
            return

        # Attempt table creation in a separate transaction
        try:
            with self._engine.begin() as conn:
                conn.execute(
                    text(
                        "CREATE TABLE IF NOT EXISTS context_map_embeddings ("
                        "  corpus_key TEXT NOT NULL,"
                        "  entry_key TEXT NOT NULL,"
                        "  embedding vector(384) NOT NULL,"
                        "  PRIMARY KEY (corpus_key, entry_key)"
                        ")"
                    )
                )
            self._copt_available = True
        except Exception:
            _log.warning(
                "pgvector embeddings table creation failed — CopT gate disabled.",
                exc_info=True,
            )
            self._copt_available = False

    def copt_upsert_embeddings(
        self,
        corpus_key: str,
        entries: list[tuple[str, list[float]]],
    ) -> None:
        """Upsert embeddings for (entry_key, embedding) pairs in a single batch."""
        if not entries or not self.copt_is_available():
            return
        params = [
            {"ck": corpus_key, "ek": ek, "emb": _serialize_embedding(emb)} for ek, emb in entries
        ]
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO context_map_embeddings "
                    "(corpus_key, entry_key, embedding) "
                    "VALUES (:ck, :ek, :emb) "
                    "ON CONFLICT (corpus_key, entry_key) "
                    "DO UPDATE SET embedding = EXCLUDED.embedding"
                ),
                params,
            )

    def copt_query_similarity(
        self,
        corpus_key: str,
        embedding: list[float],
    ) -> float:
        """Return max cosine similarity for the query embedding in the corpus."""
        if not self.copt_is_available():
            return 0.0
        with self._engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT 1.0 - (embedding <=> :query) AS similarity "
                    "FROM context_map_embeddings "
                    "WHERE corpus_key = :ck "
                    "ORDER BY embedding <=> :query LIMIT 1"
                ),
                {"ck": corpus_key, "query": _serialize_embedding(embedding)},
            ).first()
        return float(row[0]) if row is not None else 0.0

    def copt_get_all_embeddings(
        self,
        corpus_key: str,
    ) -> list[tuple[str, list[float]]]:
        """Return all stored (entry_key, embedding) pairs for a corpus.

        Used by the CopT gate to fetch stored embeddings once and compute
        similarities in Python instead of making N individual pgvector queries.
        """
        if not self.copt_is_available():
            return []
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT entry_key, embedding FROM context_map_embeddings WHERE corpus_key = :ck"
                ),
                {"ck": corpus_key},
            ).all()
        return [(str(row[0]), _deserialize_embedding(str(row[1]))) for row in rows]

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(tz=UTC).isoformat(timespec="seconds")

    @staticmethod
    def _decode_payload(payload: str) -> dict[str, Any] | str:
        try:
            decoded = json.loads(payload)
        except json.JSONDecodeError:
            return payload
        if isinstance(decoded, dict):
            return decoded
        return payload


def _serialize_embedding(embedding: list[float]) -> str:
    """Serialize a list of floats to pgvector-compatible string.

    Converts numpy scalars to native Python floats so str() produces
    ``[0.1, 0.2, …]`` instead of ``[np.float64(0.1), …]``.
    """
    return str([float(x) for x in embedding])


def _deserialize_embedding(raw: str) -> list[float]:
    """Parse a pgvector-serialized embedding string back to a float list.

    pgvector stores vectors as strings like ``[0.1, 0.2, 0.3]``.
    psycopg2 returns these as strings when not using the pgvector Python
    adapter, so we parse them manually.
    """
    import json

    return [float(x) for x in json.loads(raw)]


