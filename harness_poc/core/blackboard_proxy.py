from __future__ import annotations

from typing import TYPE_CHECKING, Any

from harness_poc.core.permissions import SkillPermissions

if TYPE_CHECKING:
    from harness_poc.core.database import BlackboardDatabase
    from harness_poc.core.state import StatePayload, StateProposal


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

    def __init__(
        self, db: BlackboardDatabase, permissions: SkillPermissions
    ) -> None:
        self._db = db
        self._permissions = permissions

    # ---- guards ----

    def _require_read(self) -> None:
        if not self._permissions.can_read_blackboard:
            raise PermissionError(
                f"Skill has blackboard={self._permissions.blackboard!r} "
                f"— cannot read from blackboard."
            )

    def _require_write(self) -> None:
        if not self._permissions.can_write_blackboard:
            raise PermissionError(
                f"Skill has blackboard={self._permissions.blackboard!r} "
                f"— cannot write to blackboard."
            )

    # ---- read methods (allowed with "read" or "read_write") ----

    def read_memory(
        self, session_id: str, key: str
    ) -> dict[str, Any] | str | None:
        self._require_read()
        return self._db.read_memory(session_id, key)

    def list_memory_keys(self, session_id: str) -> list[str]:
        self._require_read()
        return self._db.list_memory_keys(session_id)

    # ---- write methods (allowed only with "read_write") ----

    def write_memory(
        self, session_id: str, key: str, payload: str | dict[str, Any]
    ) -> None:
        self._require_write()
        self._db.write_memory(session_id, key, payload)

    def ensure_session_state(self, session_id: str) -> StatePayload:
        self._require_write()
        return self._db.ensure_session_state(session_id)

    def create_state_proposal(self, session_id: str) -> StateProposal:
        self._require_write()
        return self._db.create_state_proposal(session_id)

    def approve_state_proposal(
        self, proposal_id: str, project_id: str = "default"
    ) -> StatePayload:
        self._require_write()
        return self._db.approve_state_proposal(proposal_id, project_id)
