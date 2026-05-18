from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Literal, cast

from harness_poc.core.skill_context import SkillContext, SkillResult

if TYPE_CHECKING:
    from harness_poc.core.state import StatePayload

Mode = Literal["preview", "propose", "approve"]


def execute(ctx: SkillContext, arguments: dict[str, Any]) -> SkillResult:
    mode = _mode(str(arguments.get("mode") or "preview"))
    project_id = str(arguments.get("project_id") or "default").strip() or "default"
    session_state = ctx.database.ensure_session_state(ctx.session_id)
    if session_state.is_empty():
        return SkillResult(
            status="blocked",
            content="Current session state is empty; nothing to consolidate.",
            artifacts={
                "mode": mode,
                "project_id": project_id,
                "session_id": ctx.session_id,
            },
        )

    if mode == "preview":
        return _preview_result(
            mode=mode,
            project_id=project_id,
            session_id=ctx.session_id,
            session_state=session_state,
        )

    proposal = ctx.database.create_state_proposal(ctx.session_id)
    if mode == "propose":
        payload = {
            "mode": mode,
            "project_id": project_id,
            "session_id": ctx.session_id,
            "proposal_id": proposal.proposal_id,
            "proposal_status": proposal.status,
            "state": proposal.payload.to_dict(),
        }
        return SkillResult(
            status="success",
            content=json.dumps(payload, indent=2, sort_keys=True),
            artifacts=payload,
        )

    project_state = ctx.database.approve_state_proposal(
        proposal_id=proposal.proposal_id,
        project_id=project_id,
    )
    payload = {
        "mode": mode,
        "project_id": project_id,
        "session_id": ctx.session_id,
        "proposal_id": proposal.proposal_id,
        "proposal_status": "approved",
        "project_state": project_state.to_dict(),
    }
    return SkillResult(
        status="success",
        content=json.dumps(payload, indent=2, sort_keys=True),
        artifacts=payload,
    )


def _preview_result(
    *,
    mode: Mode,
    project_id: str,
    session_id: str,
    session_state: StatePayload,
) -> SkillResult:
    payload = {
        "mode": mode,
        "project_id": project_id,
        "session_id": session_id,
        "proposal_status": "not_created",
        "state": session_state.to_dict(),
    }
    return SkillResult(
        status="success",
        content=session_state.to_markdown("Session State To Consolidate"),
        artifacts=payload,
    )


def _mode(value: str) -> Mode:
    normalized = value.strip().lower()
    if normalized in {"preview", "propose", "approve"}:
        return cast("Mode", normalized)
    msg = "consolidate_state mode must be preview, propose, or approve"
    raise ValueError(msg)
