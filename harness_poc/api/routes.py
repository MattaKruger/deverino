from __future__ import annotations

from fastapi import APIRouter, Query, Request

from harness_poc.core.observability.dashboard import (
    ContextMapEntrySummary,
    ContextMapHealth,
    DashboardSnapshot,
    ErrorSummary,
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
def get_session_events(
    request: Request, session_id: str
) -> list[SessionEventRow]:
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
def get_context_map_entries(
    request: Request, key: str
) -> list[ContextMapEntrySummary]:
    return fetch_context_map_entries(_engine(request), key)


@router.get("/api/events/recent")
def get_recent_events(
    request: Request, limit: int = Query(default=50)
) -> list[UnifiedEvent]:
    return fetch_recent_events(_engine(request), limit=limit)


@router.get("/api/errors")
def get_errors(request: Request) -> list[ErrorSummary]:
    return fetch_error_summary(_engine(request))


@router.get("/api/corpora/keys")
def get_corpora_keys(request: Request) -> list[str]:
    return fetch_corpus_keys(_engine(request))
