from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from harness_poc.core.context_map.schema import MapEntry
    from harness_poc.core.events import ContextMapEvent
    from harness_poc.core.permissions import SkillPermissions
    from harness_poc.core.storage.database import BlackboardDatabase
    from harness_poc.core.storage.models import DbDocumentChunk, DbDocumentSource
    from harness_poc.core.storage.state import StatePayload, StateProposal


class BlackboardAccessProxy:
    """Wraps ``BlackboardDatabase`` and enforces skill permissions.

    Every method gates on the skill's ``blackboard`` permission level:
      - ``"none"`` → all methods raise ``PermissionError``
      - ``"read"`` → read methods pass, write methods raise
      - ``"read_write"`` → all methods pass

    The proxy mirrors exactly the subset of ``BlackboardDatabase`` methods
    that skills actually call. If a new skill method is added to the database,
    it must be mirrored here (or the skill will get a raw ``AttributeError``).
    """

    def __init__(self, db: BlackboardDatabase, permissions: SkillPermissions) -> None:
        self._db = db
        self._permissions = permissions

    # ---- guards ----

    def _require_read(self) -> None:
        if not self._permissions.can_read_blackboard:
            msg = (
                f"Skill has blackboard={self._permissions.blackboard!r} "
                f"— cannot read from blackboard."
            )
            raise PermissionError(msg)

    def _require_write(self) -> None:
        if not self._permissions.can_write_blackboard:
            msg = (
                f"Skill has blackboard={self._permissions.blackboard!r} "
                f"— cannot write to blackboard."
            )
            raise PermissionError(msg)

    # ---- read methods (allowed with "read" or "read_write") ----

    def read_memory(self, session_id: str, key: str) -> dict[str, Any] | str | None:
        self._require_read()
        return self._db.read_memory(session_id, key)

    def list_memory_keys(self, session_id: str) -> list[str]:
        self._require_read()
        return self._db.list_memory_keys(session_id)

    # ---- write methods (allowed only with "read_write") ----

    def write_memory(self, session_id: str, key: str, payload: str | dict[str, Any]) -> None:
        self._require_write()
        self._db.write_memory(session_id, key, payload)

    def ensure_session_state(self, session_id: str) -> StatePayload:
        self._require_write()
        return self._db.ensure_session_state(session_id)

    def create_state_proposal(self, session_id: str) -> StateProposal:
        self._require_write()
        return self._db.create_state_proposal(session_id)

    def approve_state_proposal(self, proposal_id: str, project_id: str = "default") -> StatePayload:
        self._require_write()
        return self._db.approve_state_proposal(proposal_id, project_id)

    # ---- document metadata read methods ----

    def get_document_source(self, source_id: str) -> DbDocumentSource | None:
        self._require_read()
        return self._db.get_document_source(source_id)

    def list_document_sources(self) -> list[DbDocumentSource]:
        self._require_read()
        return self._db.list_document_sources()

    def list_chunks_for_source(self, source_id: str) -> list[DbDocumentChunk]:
        self._require_read()
        return self._db.list_chunks_for_source(source_id)

    def get_context_map(self, corpus_key: str) -> list[MapEntry] | None:
        self._require_read()
        return self._db.get_context_map(corpus_key)

    def get_pending_context_map_events(
        self, corpus_key: str, limit: int = 50
    ) -> list[Any]:
        self._require_read()
        return self._db.get_pending_context_map_events(corpus_key, limit)

    def get_pending_corpus_keys(self) -> list[str]:
        self._require_read()
        return self._db.get_pending_corpus_keys()

    def get_and_bump_cycle(self, corpus_key: str) -> int:
        self._require_write()
        return self._db.get_and_bump_cycle(corpus_key)

    def get_cycle(self, corpus_key: str) -> int:
        self._require_read()
        return self._db.get_cycle(corpus_key)

    def get_context_maps(self, corpus_keys: list[str]) -> dict[str, list[MapEntry]]:
        self._require_read()
        return self._db.get_context_maps(corpus_keys)

    def get_all_corpus_keys(self) -> list[str]:
        self._require_read()
        return self._db.get_all_corpus_keys()

    def get_cycles(self, corpus_keys: list[str]) -> dict[str, int]:
        self._require_read()
        return self._db.get_cycles(corpus_keys)

    def read_session_state(self, session_id: str) -> StatePayload | None:
        self._require_read()
        return self._db.read_session_state(session_id)

    # ---- document metadata write methods ----

    def upsert_document_source(self, source: DbDocumentSource) -> None:
        self._require_write()
        self._db.upsert_document_source(source)

    def upsert_document_chunk(self, chunk: DbDocumentChunk) -> None:
        self._require_write()
        self._db.upsert_document_chunk(chunk)

    def append_context_map_event(self, event: ContextMapEvent) -> None:
        self._require_write()
        self._db.append_context_map_event(event)

    def write_map_and_mark_processed(
        self,
        corpus_key: str,
        map_entries: list[MapEntry],
        token_count: int,
        event_ids: list[str],
        freeze_until: str | None = None,
    ) -> None:
        self._require_write()
        self._db.write_map_and_mark_processed(
            corpus_key,
            map_entries,
            token_count,
            event_ids,
            freeze_until,
        )

    # ---- async wrappers ----

    async def read_memory_async(self, session_id: str, key: str) -> dict[str, Any] | str | None:
        self._require_read()
        return await asyncio.to_thread(self._db.read_memory, session_id, key)

    async def list_memory_keys_async(self, session_id: str) -> list[str]:
        self._require_read()
        return await asyncio.to_thread(self._db.list_memory_keys, session_id)

    async def write_memory_async(
        self, session_id: str, key: str, payload: str | dict[str, Any]
    ) -> None:
        self._require_write()
        await asyncio.to_thread(self._db.write_memory, session_id, key, payload)
