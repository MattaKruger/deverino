"""AG-UI chat endpoint — bridges PydanticAgentRuntime to AG-UI SSE events.

Uses ``AGUIAdapter.dispatch_request()`` from pydantic-ai, which handles
request parsing, agent execution, event encoding, and SSE streaming
automatically.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from harness_poc.core.config import HarnessConfig
from harness_poc.core.runtime.pydantic_runtime import PydanticAgentRuntime
from harness_poc.core.storage.database import BlackboardDatabase

router = APIRouter()


# ── Session management ────────────────────────────────────────────────────────


@router.get("/api/sessions/chat")
def list_chat_sessions(request: Request, limit: int = 20) -> list[dict[str, Any]]:
    """List recent active chat sessions with message counts."""
    db = BlackboardDatabase(request.app.state.engine)
    return db.list_recent_sessions(limit=limit)


@router.post("/api/sessions/chat")
def create_chat_session(request: Request) -> dict[str, str]:
    """Create a new chat session and return its ID."""
    db = BlackboardDatabase(request.app.state.engine)
    session_id = db.start_session(objective="Web chat session")
    return {"session_id": session_id}


@router.delete("/api/sessions/chat/{session_id}")
def delete_chat_session(session_id: str, request: Request) -> dict[str, str]:
    """Soft-delete (archive) a chat session."""
    db = BlackboardDatabase(request.app.state.engine)
    if db.delete_session(session_id):
        return {"status": "archived"}
    raise HTTPException(status_code=404, detail="Session not found")


@router.get("/api/sessions/chat/{session_id}/history")
def get_chat_history(session_id: str, request: Request) -> list[dict[str, Any]]:
    """Return the raw message history for a session."""
    db = BlackboardDatabase(request.app.state.engine)
    if not db.session_exists(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    return db.load_session_messages(session_id)


# ── AG-UI chat endpoint ───────────────────────────────────────────────────────


@router.post("/api/chat")
async def chat_endpoint(request: Request) -> Response:
    """AG-UI chat endpoint.

    ``AGUIAdapter.dispatch_request()`` handles the full lifecycle:
    parse ``RunAgentInput`` from the request body, run the agent with
    tool-calling, encode events, and stream the SSE response.
    """
    from pydantic_ai.ui.ag_ui import AGUIAdapter  # noqa: PLC0415

    config = getattr(request.app.state, "config", None) or HarnessConfig.load()
    if not hasattr(request.app.state, "chat_runtimes"):
        request.app.state.chat_runtimes: dict[str, PydanticAgentRuntime] = {}

    # ── Resolve session ──────────────────────────────────────────────────
    session_id = _extract_session_id(request)
    db = BlackboardDatabase(request.app.state.engine)

    # ── Build or reuse runtime (cold start is ~30s for imports) ────────────
    runtime = request.app.state.chat_runtimes.get(session_id)
    if runtime is None:
        runtime = _build_chat_runtime(session_id, db, config)
        request.app.state.chat_runtimes[session_id] = runtime

    message_history_raw = db.load_session_messages(session_id)
    message_history = _deserialize_messages(message_history_raw)

    # ── Delegate to AGUIAdapter ───────────────────────────────────────────
    return await AGUIAdapter.dispatch_request(
        request,
        agent=runtime.agent,
        deps=runtime.deps,
        message_history=message_history or None,
        conversation_id=session_id,
    )


# ── Cancellation ───────────────────────────────────────────────────────────────


@router.post("/api/chat/{session_id}/cancel")
def cancel_chat(session_id: str, request: Request) -> dict[str, str]:
    """Cancel an in-flight chat turn."""
    token = request.app.state.active_tokens.get(session_id)
    if token is not None:
        token.cancel("User requested cancellation")
        return {"status": "cancelled"}
    return {"status": "no_active_turn"}


# ── Helpers ────────────────────────────────────────────────────────────────────


def _extract_session_id(request: Request) -> str:
    """Extract session_id from query param, falling back to a new UUID."""
    session_id = request.query_params.get("session_id")
    return session_id or str(uuid.uuid4())


def _build_chat_runtime(
    session_id: str,
    db: BlackboardDatabase,
    config: HarnessConfig,
) -> PydanticAgentRuntime:
    """Build a lightweight PydanticAgentRuntime for a chat session.

    Reuses the same construction as the TUI/REPL (``build_primary_agent``
    + ``AgentDeps``), but skips context maps, skill catalogs, workflows,
    and pipelines — just the agent with tools.
    """
    from harness_poc.core.runtime.pydantic_runtime import (  # noqa: PLC0415
        AgentDeps,
        build_primary_agent,
    )
    from harness_poc.core.skills import SkillRunner  # noqa: PLC0415
    from harness_poc.core.tools import ToolRunner  # noqa: PLC0415

    # ── System prompt ─────────────────────────────────────────────────────
    soul_path = config.paths.soul
    system_prompt = soul_path.read_text(encoding="utf-8") if soul_path.exists() else ""

    # ── Skill & tool runners ──────────────────────────────────────────────
    skill_runner = SkillRunner(database=db, config=config)
    tool_runner = ToolRunner(
        config=config,
        skill_runner=skill_runner,
        database=db,
        runtime_config=config.runtime,
    )

    # ── Block TUI-specific skills in web context ──────────────────────────
    _web_blocked = frozenset(
        {
            "append_event",
            "consolidate_state",
            "read_memory",
            "summarize_memory",
            "inspect_db",
            "trace_session",
        }
    )

    # ── Agent ─────────────────────────────────────────────────────────────
    agent = build_primary_agent(
        system_prompt=system_prompt,
        skill_runner=skill_runner,
        tool_runner=tool_runner,
        llm=config.llm,
        enable_tools=True,
        blocked_skills=_web_blocked,
    )

    deps = AgentDeps(
        session_id=session_id,
        database=db,
        config=config,
        skill_runner=skill_runner,
        tool_runner=tool_runner,
    )

    return PydanticAgentRuntime(agent=agent, deps=deps)


def _deserialize_messages(raw: list[dict[str, Any]]) -> list[Any]:
    """Deserialize message dicts back to PydanticAI ModelMessage objects."""
    if not raw:
        return []
    try:
        from pydantic_ai.messages import ModelMessagesTypeAdapter  # noqa: PLC0415

        return ModelMessagesTypeAdapter.validate_python(raw)
    except Exception:
        return []
