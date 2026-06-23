from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from harness_poc.core.permissions import SkillPermissions
    from harness_poc.core.storage.database import BlackboardDatabase

# ponytail: classify write vs read; __getattr__ delegates the rest
# upgrade: test_blackboard_proxy_coverage.py fails if a new write-named db method is unclassified
_WRITE_METHODS: frozenset[str] = frozenset({
    "append_context_map_event",
    "append_session_messages",
    "append_session_state",
    "approve_latest_proposal",
    "approve_state_proposal",
    "copt_upsert_embeddings",
    "create_state_proposal",
    "create_tables",
    "ensure_session_state",
    "get_and_bump_cycle",
    "reject_state_proposal",
    "set_map_freeze",
    "set_project_fact",
    "start_session",
    "upsert_document_chunk",
    "upsert_document_source",
    "upsert_materialized_context_map",
    "write_map_and_mark_processed",
    "write_memory",
})


class BlackboardAccessProxy:
    """Wraps BlackboardDatabase and enforces skill permissions.

    Permission levels: "none" → all raise; "read" → reads pass; "read_write" → all pass.
    New BlackboardDatabase methods are available automatically via __getattr__.
    """

    def __init__(self, db: BlackboardDatabase, permissions: SkillPermissions) -> None:
        self._db = db
        self._permissions = permissions

    def _require_read(self) -> None:
        if not self._permissions.can_read_blackboard:
            msg = f"Skill has blackboard={self._permissions.blackboard!r} — cannot read from blackboard."
            raise PermissionError(msg)

    def _require_write(self) -> None:
        if not self._permissions.can_write_blackboard:
            msg = f"Skill has blackboard={self._permissions.blackboard!r} — cannot write to blackboard."
            raise PermissionError(msg)

    def __getattr__(self, name: str) -> Any:  # noqa: ANN401
        if name in _WRITE_METHODS:
            self._require_write()
        else:
            self._require_read()
        return getattr(self._db, name)

    # Async wrappers — these don't exist on BlackboardDatabase, so explicit definition is needed.

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
