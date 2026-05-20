from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlmodel import Session, col, select

if TYPE_CHECKING:
    from sqlalchemy import Engine

    from harness_poc.core.context_map_events import ContextMapEvent

from harness_poc.core.db_engine import create_db_engine
from harness_poc.core.models import (
    DbContextMap,
    DbContextMapEvent,
    DbDocumentChunk,
    DbDocumentSource,
    DbProjectState,
    DbSession,
    DbSessionState,
    DbSharedMemory,
    DbStateEvent,
    DbStateProposal,
    SQLModel,
)
from harness_poc.core.state import StatePayload, StateProposal, StateSection


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

    def start_session(self, objective: str) -> str:
        session_id = str(uuid.uuid4())
        with Session(self._engine) as session:
            session.add(
                DbSession(
                    session_id=session_id,
                    global_objective=objective,
                    status="active",
                    created_at=self._utc_now(),
                )
            )
            session.commit()
        return session_id

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
        session_state = self.ensure_session_state(session_id)
        if session_state.is_empty():
            msg = "Session state is empty; nothing to propose"
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
        now = self._utc_now()
        with Session(self._engine) as session:
            proposal_row = session.get(DbStateProposal, proposal_id)
            if proposal_row is None:
                msg = f"State proposal not found: {proposal_id}"
                raise ValueError(msg)
            if proposal_row.status != "pending":
                msg = f"State proposal is not pending: {proposal_id}"
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
        now = self._utc_now()
        with Session(self._engine) as session:
            proposal_row = session.get(DbStateProposal, proposal_id)
            if proposal_row is None:
                msg = f"State proposal not found: {proposal_id}"
                raise ValueError(msg)
            if proposal_row.status != "pending":
                msg = f"State proposal is not pending: {proposal_id}"
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

    def upsert_document_source(self, source: DbDocumentSource) -> None:
        with Session(self._engine) as session:
            existing = session.get(DbDocumentSource, source.source_id)
            if existing is None:
                session.add(source)
            else:
                existing.uri = source.uri
                existing.title = source.title
                existing.kind = source.kind
                existing.content_hash = source.content_hash
                existing.status = source.status
                existing.chunk_count = source.chunk_count
                existing.indexed_at = source.indexed_at
                existing.error = source.error
                existing.metadata_payload = source.metadata_payload
                existing.updated_at = source.updated_at
                session.add(existing)
            session.commit()

    def get_document_source(self, source_id: str) -> DbDocumentSource | None:
        with Session(self._engine) as session:
            return session.get(DbDocumentSource, source_id)

    def list_document_sources(self) -> list[DbDocumentSource]:
        with Session(self._engine) as session:
            return list(session.exec(select(DbDocumentSource)).all())

    def upsert_document_chunk(self, chunk: DbDocumentChunk) -> None:
        with Session(self._engine) as session:
            existing = session.get(DbDocumentChunk, chunk.chunk_id)
            if existing is None:
                session.add(chunk)
            else:
                existing.source_id = chunk.source_id
                existing.chunk_index = chunk.chunk_index
                existing.content_hash = chunk.content_hash
                existing.vespa_id = chunk.vespa_id
                existing.indexed_at = chunk.indexed_at
                session.add(existing)
            session.commit()

    def list_chunks_for_source(self, source_id: str) -> list[DbDocumentChunk]:
        with Session(self._engine) as session:
            return list(
                session.exec(
                    select(DbDocumentChunk).where(DbDocumentChunk.source_id == source_id)
                ).all()
            )

    def append_context_map_event(self, event: ContextMapEvent) -> None:
        with Session(self._engine) as session:
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

    def get_context_map(self, corpus_key: str) -> dict[str, Any] | None:
        with Session(self._engine) as session:
            row = session.get(DbContextMap, corpus_key)
        if row is None:
            return None
        try:
            return json.loads(row.map_json)
        except json.JSONDecodeError:
            return None

    def write_map_and_mark_processed(
        self,
        corpus_key: str,
        map_json: dict[str, Any],
        token_count: int,
        event_ids: list[str],
    ) -> None:
        now = self._utc_now()
        serialized = json.dumps(map_json, sort_keys=True)
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
                    )
                )
            else:
                row.map_json = serialized
                row.token_count = token_count
                row.version += 1
                row.last_updated = now
                session.add(row)
            for event_id in event_ids:
                event_row = session.get(DbContextMapEvent, event_id)
                if event_row is not None:
                    event_row.processed = 1
                    session.add(event_row)
            session.commit()

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
