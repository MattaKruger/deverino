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

    Reuses the same construction path as the TUI/REPL for the agent,
    available toolset, skill catalog, and knowledge skill context. Web chat
    still skips TUI-only workflows/pipelines, but the model sees the same
    skill catalog and ``skills_list``/``skill_view`` context.
    """
    from harness_poc.app_factory import _TUI_BLOCKED_SKILLS  # noqa: PLC0415
    from harness_poc.core.permissions import SkillPermissions  # noqa: PLC0415
    from harness_poc.core.runtime.pydantic_runtime import build_runtime  # noqa: PLC0415
    from harness_poc.core.skills import SkillRunner, build_skill_catalog  # noqa: PLC0415
    from harness_poc.core.storage import BlackboardAccessProxy  # noqa: PLC0415
    from harness_poc.core.tools import ToolRunner  # noqa: PLC0415
    from harness_poc.system_tools.knowledge_tools import init_knowledge_context  # noqa: PLC0415

    # ── System prompt ─────────────────────────────────────────────────────
    soul_path = config.paths.soul
    system_prompt = soul_path.read_text(encoding="utf-8") if soul_path.exists() else ""

    # ── Skill & tool runners ──────────────────────────────────────────────
    skill_runner = SkillRunner(database=db, config=config)
    db_proxy = BlackboardAccessProxy(
        db,
        SkillPermissions(blackboard="read_write", workspace="read_write"),
    )
    tool_runner = ToolRunner(
        config=config,
        skill_runner=skill_runner,
        database=db_proxy,
        runtime_config=config.runtime,
    )

    # ── Knowledge skill context and catalog ───────────────────────────────
    knowledge_dirs = [config.paths.project_skills]
    if config.paths.system_skills.exists():
        knowledge_dirs.append(config.paths.system_skills)

    init_knowledge_context(
        knowledge_dirs,
        project_root=config.project_root,
        scratch_base=None,
        session_id=session_id,
        skill_runner=skill_runner,
    )
    skill_catalog = build_skill_catalog(knowledge_dirs)

    # ── Agent ─────────────────────────────────────────────────────────────
    runtime = build_runtime(
        session_id=session_id,
        database=db,
        config=config,
        skill_runner=skill_runner,
        tool_runner=tool_runner,
        system_prompt=system_prompt,
        llm=config.llm,
        enable_tools=True,
        blocked_skills=_TUI_BLOCKED_SKILLS,
        skill_catalog=skill_catalog,
    )
    tool_runner.system_prompt = "\n\n".join(runtime.agent._system_prompts)  # noqa: SLF001

    return runtime


def _deserialize_messages(raw: list[dict[str, Any]]) -> list[Any]:
    """Deserialize message dicts back to PydanticAI ModelMessage objects."""
    if not raw:
        return []
    try:
        from pydantic_ai.messages import ModelMessagesTypeAdapter  # noqa: PLC0415

        return ModelMessagesTypeAdapter.validate_python(raw)
    except Exception:
        return []
