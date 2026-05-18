from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from harness_poc.core.state import StatePayload, StateProposal, StateSection


@dataclass(frozen=True, slots=True)
class SessionRow:
    session_id: str
    global_objective: str
    status: str
    created_at: str


@dataclass(frozen=True, slots=True)
class MemoryRow:
    id: int
    session_id: str
    memory_key: str
    data_payload: str
    created_at: str


class BlackboardDatabase:
    def __init__(self, database_path: Path | str = "blackboard.db") -> None:
        self.database_path = Path(database_path)

    def create_tables(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    global_objective TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TIMESTAMP NOT NULL
                )
                """,
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS shared_memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    memory_key TEXT NOT NULL,
                    data_payload TEXT NOT NULL,
                    created_at TIMESTAMP NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
                )
                """,
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_shared_memory_session_key
                ON shared_memory (session_id, memory_key, created_at DESC)
                """,
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS project_state (
                    project_id TEXT PRIMARY KEY,
                    state_payload TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    updated_at TIMESTAMP NOT NULL
                )
                """,
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS session_state (
                    session_id TEXT PRIMARY KEY,
                    state_payload TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    dirty INTEGER NOT NULL,
                    updated_at TIMESTAMP NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
                )
                """,
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS state_proposals (
                    proposal_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    proposal_payload TEXT NOT NULL,
                    created_at TIMESTAMP NOT NULL,
                    resolved_at TIMESTAMP,
                    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
                )
                """,
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS state_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scope TEXT NOT NULL,
                    scope_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TIMESTAMP NOT NULL
                )
                """,
            )

    def start_session(self, objective: str) -> str:
        session_id = str(uuid.uuid4())
        created_at = self._utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO sessions (session_id, global_objective, status, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (session_id, objective, "active", created_at),
            )
        return session_id

    def write_memory(
        self, session_id: str, key: str, payload: str | dict[str, Any]
    ) -> None:
        data_payload = (
            json.dumps(payload, sort_keys=True)
            if isinstance(payload, dict)
            else payload
        )
        created_at = self._utc_now()
        with self._connect() as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute(
                """
                INSERT INTO shared_memory (session_id, memory_key, data_payload, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (session_id, key, data_payload, created_at),
            )

    def read_memory(
        self, session_id: str, key: str
    ) -> dict[str, Any] | str | None:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                SELECT id, session_id, memory_key, data_payload, created_at
                FROM shared_memory
                WHERE session_id = ? AND memory_key = ?
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """,
                (session_id, key),
            )
            row = cursor.fetchone()

        if row is None:
            return None

        memory_row = MemoryRow(
            id=int(row["id"]),
            session_id=str(row["session_id"]),
            memory_key=str(row["memory_key"]),
            data_payload=str(row["data_payload"]),
            created_at=str(row["created_at"]),
        )
        return self._decode_payload(memory_row.data_payload)

    def list_memory_keys(self, session_id: str) -> list[str]:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                SELECT DISTINCT memory_key
                FROM shared_memory
                WHERE session_id = ?
                ORDER BY memory_key ASC
                """,
                (session_id,),
            )
            return [str(row["memory_key"]) for row in cursor.fetchall()]

    def ensure_project_state(self, project_id: str = "default") -> StatePayload:
        payload = self.read_project_state(project_id)
        if payload is not None:
            return payload
        empty_state = StatePayload()
        now = self._utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO project_state (project_id, state_payload, version, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (project_id, self._encode_state(empty_state), 1, now),
            )
        return empty_state

    def read_project_state(
        self, project_id: str = "default"
    ) -> StatePayload | None:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                SELECT state_payload
                FROM project_state
                WHERE project_id = ?
                """,
                (project_id,),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return self._decode_state(str(row["state_payload"]))

    def ensure_session_state(self, session_id: str) -> StatePayload:
        payload = self.read_session_state(session_id)
        if payload is not None:
            return payload
        empty_state = StatePayload()
        now = self._utc_now()
        with self._connect() as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute(
                """
                INSERT INTO session_state (session_id, state_payload, version, dirty, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, self._encode_state(empty_state), 1, 0, now),
            )
        return empty_state

    def read_session_state(self, session_id: str) -> StatePayload | None:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                SELECT state_payload
                FROM session_state
                WHERE session_id = ?
                """,
                (session_id,),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return self._decode_state(str(row["state_payload"]))

    def append_session_state(
        self,
        session_id: str,
        section: StateSection,
        text: str,
    ) -> StatePayload:
        current_state = self.ensure_session_state(session_id)
        next_state = current_state.append(section, text)
        now = self._utc_now()
        with self._connect() as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute(
                """
                UPDATE session_state
                SET state_payload = ?, version = version + 1, dirty = 1, updated_at = ?
                WHERE session_id = ?
                """,
                (self._encode_state(next_state), now, session_id),
            )
            connection.execute(
                """
                INSERT INTO state_events (scope, scope_id, event_type, payload, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    "session",
                    session_id,
                    f"append_{section}",
                    json.dumps({"text": text}, sort_keys=True),
                    now,
                ),
            )
        return next_state

    def create_state_proposal(self, session_id: str) -> StateProposal:
        session_state = self.ensure_session_state(session_id)
        if session_state.is_empty():
            msg = "Session state is empty; nothing to propose"
            raise ValueError(msg)
        proposal = StateProposal.create(
            session_id=session_id, payload=session_state
        )
        now = self._utc_now()
        with self._connect() as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute(
                """
                INSERT INTO state_proposals (
                    proposal_id,
                    session_id,
                    status,
                    proposal_payload,
                    created_at,
                    resolved_at
                )
                VALUES (?, ?, ?, ?, ?, NULL)
                """,
                (
                    proposal.proposal_id,
                    proposal.session_id,
                    proposal.status,
                    proposal.to_database_payload(),
                    now,
                ),
            )
            connection.execute(
                """
                INSERT INTO state_events (scope, scope_id, event_type, payload, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    "session",
                    session_id,
                    "proposal_created",
                    json.dumps(
                        {"proposal_id": proposal.proposal_id}, sort_keys=True
                    ),
                    now,
                ),
            )
        return proposal

    def read_state_proposal(self, proposal_id: str) -> StateProposal | None:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                SELECT proposal_id, session_id, status, proposal_payload
                FROM state_proposals
                WHERE proposal_id = ?
                """,
                (proposal_id,),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return StateProposal.from_row_payload(
            proposal_id=str(row["proposal_id"]),
            session_id=str(row["session_id"]),
            status=str(row["status"]),
            proposal_payload=str(row["proposal_payload"]),
        )

    def approve_state_proposal(
        self,
        proposal_id: str,
        project_id: str = "default",
    ) -> StatePayload:
        proposal = self.read_state_proposal(proposal_id)
        if proposal is None:
            msg = f"State proposal not found: {proposal_id}"
            raise ValueError(msg)
        if proposal.status != "pending":
            msg = f"State proposal is not pending: {proposal_id}"
            raise ValueError(msg)

        current_project_state = self.ensure_project_state(project_id)
        next_project_state = current_project_state.append_payload(
            proposal.payload
        )
        now = self._utc_now()
        with self._connect() as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute(
                """
                UPDATE project_state
                SET state_payload = ?, version = version + 1, updated_at = ?
                WHERE project_id = ?
                """,
                (self._encode_state(next_project_state), now, project_id),
            )
            connection.execute(
                """
                UPDATE state_proposals
                SET status = ?, resolved_at = ?
                WHERE proposal_id = ?
                """,
                ("approved", now, proposal_id),
            )
            connection.execute(
                """
                UPDATE session_state
                SET dirty = 0, updated_at = ?
                WHERE session_id = ?
                """,
                (now, proposal.session_id),
            )
            connection.execute(
                """
                INSERT INTO state_events (scope, scope_id, event_type, payload, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    "project",
                    project_id,
                    "proposal_approved",
                    json.dumps(
                        {
                            "proposal_id": proposal_id,
                            "session_id": proposal.session_id,
                        },
                        sort_keys=True,
                    ),
                    now,
                ),
            )
        return next_project_state

    def approve_latest_proposal(
        self, project_id: str = "default"
    ) -> StatePayload:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                SELECT proposal_id
                FROM state_proposals
                WHERE status = 'pending'
                ORDER BY created_at DESC
                LIMIT 1
                """,
            )
            row = cursor.fetchone()
        if row is None:
            msg = "No pending state proposals found"
            raise ValueError(msg)
        return self.approve_state_proposal(
            proposal_id=str(row["proposal_id"]),
            project_id=project_id,
        )

    def reject_state_proposal(self, proposal_id: str) -> None:
        proposal = self.read_state_proposal(proposal_id)
        if proposal is None:
            msg = f"State proposal not found: {proposal_id}"
            raise ValueError(msg)
        if proposal.status != "pending":
            msg = f"State proposal is not pending: {proposal_id}"
            raise ValueError(msg)

        now = self._utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE state_proposals
                SET status = ?, resolved_at = ?
                WHERE proposal_id = ?
                """,
                ("rejected", now, proposal_id),
            )
            connection.execute(
                """
                INSERT INTO state_events (scope, scope_id, event_type, payload, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    "session",
                    proposal.session_id,
                    "proposal_rejected",
                    json.dumps({"proposal_id": proposal_id}, sort_keys=True),
                    now,
                ),
            )

    def _connect(self) -> sqlite3.Connection:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database_path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        return connection

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

    @staticmethod
    def _encode_state(state: StatePayload) -> str:
        return json.dumps(state.to_dict(), sort_keys=True)

    @staticmethod
    def _decode_state(payload: str) -> StatePayload:
        decoded = json.loads(payload)
        if not isinstance(decoded, dict):
            msg = "Stored state payload must be a JSON object"
            raise TypeError(msg)
        return StatePayload.from_dict(decoded)
