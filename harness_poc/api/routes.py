from __future__ import annotations

import asyncio
import dataclasses
import json

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from harness_poc.core.observability.dashboard import (
    ContextMapEntrySummary,
    ContextMapHealth,
    DashboardSnapshot,
    ErrorSummary,
    EventDetail,
    SessionActivity,
    SessionEventRow,
    SubAgentNode,
    TokenBucket,
    UnifiedEvent,
    fetch_context_map_entries,
    fetch_context_map_health,
    fetch_corpus_keys,
    fetch_dashboard_snapshot,
    fetch_error_summary,
    fetch_event_detail,
    fetch_model_token_usage,
    fetch_recent_events,
    fetch_session_activity,
    fetch_session_events,
    fetch_session_token_usage,
    fetch_skill_performance,
    fetch_sub_agent_tree,
    fetch_token_buckets,
    fetch_tool_latency,
)

router = APIRouter()


def _engine(request: Request):
    return request.app.state.engine


@router.get("/api/overview")
def get_overview(request: Request) -> DashboardSnapshot:
    return fetch_dashboard_snapshot(_engine(request))


@router.get("/api/sessions")
def get_sessions(request: Request) -> list[SessionActivity]:
    return fetch_session_activity(_engine(request), limit=12)


@router.get("/api/sessions/{session_id}/events")
def get_session_events(request: Request, session_id: str) -> list[SessionEventRow]:
    return fetch_session_events(_engine(request), session_id)


@router.get("/api/tools/performance")
def get_tools_performance(request: Request) -> dict[str, object]:
    engine = _engine(request)
    return {
        "skills": fetch_skill_performance(engine),
        "latency": fetch_tool_latency(engine),
    }


@router.get("/api/subagents/tree")
def get_subagents_tree(request: Request) -> list[SubAgentNode]:
    return fetch_sub_agent_tree(_engine(request))


@router.get("/api/tokens/economics")
def get_tokens_economics(request: Request) -> list[TokenBucket]:
    return fetch_token_buckets(_engine(request))


@router.get("/api/tokens/usage")
def get_tokens_usage(request: Request) -> dict[str, object]:
    engine = _engine(request)
    return {
        "models": fetch_model_token_usage(engine),
        "sessions": fetch_session_token_usage(engine),
    }


@router.get("/api/context-maps")
def get_context_maps(request: Request) -> list[ContextMapHealth]:
    return fetch_context_map_health(_engine(request))


@router.get("/api/context-maps/{key}/entries")
def get_context_map_entries(request: Request, key: str) -> list[ContextMapEntrySummary]:
    return fetch_context_map_entries(_engine(request), key)


@router.get("/api/events/stream")
async def stream_events(request: Request, limit: int = Query(default=50)) -> StreamingResponse:
    """Server-Sent Events stream of recent events."""
    engine = _engine(request)

    async def event_generator():
        while True:
            if await request.is_disconnected():
                break

            events = fetch_recent_events(engine, limit=limit)
            for e in reversed(events):  # oldest first, so frontend can prepend
                payload = json.dumps(dataclasses.asdict(e), default=str)
                yield f"data: {payload}\n\n"

            await asyncio.sleep(1)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/api/events/recent")
def get_recent_events(request: Request, limit: int = Query(default=50)) -> list[UnifiedEvent]:
    return fetch_recent_events(_engine(request), limit=limit)


@router.get("/api/events/{event_id}")
def get_event_detail(request: Request, event_id: int) -> EventDetail | None:
    return fetch_event_detail(_engine(request), event_id)


@router.get("/api/errors")
def get_errors(request: Request) -> list[ErrorSummary]:
    return fetch_error_summary(_engine(request))


@router.get("/api/corpora/keys")
def get_corpora_keys(request: Request) -> list[str]:
    return fetch_corpus_keys(_engine(request))
