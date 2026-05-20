from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlmodel import Session, select

if TYPE_CHECKING:
    from sqlalchemy import Engine

from harness_poc.core.db_engine import create_db_engine
from harness_poc.core.models import (
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
        data_payload = (
            json.dumps(payload, sort_keys=True) if isinstance(payload, dict) else payload
        )
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
                .order_by(DbSharedMemory.created_at.desc(), DbSharedMemory.id.desc())  # type: ignore[arg-type]
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
                .order_by(DbStateProposal.created_at.desc())  # type: ignore[arg-type]
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
