from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import yaml
from pydantic import ValidationError
from sqlalchemy import text

from harness_poc.core.context_map.schema import MapEntry

if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy import Engine

_log = logging.getLogger(__name__)

_CONTENT_PREVIEW_CHARS: int = 120


@dataclass(frozen=True, slots=True)
class DashboardSummary:
    total_sessions: int
    total_events: int
    total_tokens: int
    skill_calls: int
    skill_failures: int
    context_pending: int
    pending_state_proposals: int = 0


@dataclass(frozen=True, slots=True)
class SkillPerformance:
    skill_name: str
    calls: int
    failures: int
    last_status: str
    last_seen: str


@dataclass(frozen=True, slots=True)
class RecentFailure:
    event_id: int
    session_id: str
    event_type: str
    status: str
    label: str
    created_at: str
    detail: str


@dataclass(frozen=True, slots=True)
class TokenBucket:
    bucket: str
    tokens: int
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True, slots=True)
class ContextMapHealth:
    corpus_key: str
    version: int
    token_count: int
    last_updated: str
    freeze_until: str
    pending_events: int


@dataclass(frozen=True, slots=True)
class ContextMapEntrySummary:
    entry_id: str
    key: str
    section: str
    observation_type: str
    priority: float
    materialization_count: int
    token_estimate: int
    summary: str


@dataclass(frozen=True, slots=True)
class SessionActivity:
    session_id: str
    status: str
    last_event_type: str
    event_count: int
    total_tokens: int
    skill_failures: int
    last_seen: str
    goal: str


@dataclass(frozen=True, slots=True)
class ModelTokenUsage:
    model: str
    actions: int
    sessions: int
    tokens: int
    input_tokens: int
    output_tokens: int
    billable_tokens: int
    new_tokens: int


@dataclass(frozen=True, slots=True)
class SessionTokenUsage:
    session_id: str
    models: str
    actions: int
    tokens: int
    input_tokens: int
    output_tokens: int
    billable_tokens: int
    new_tokens: int
    last_seen: str


@dataclass(frozen=True, slots=True)
class SessionEventRow:
    event_id: int
    event_type: str
    created_at: str
    time_delta: float
    skill_name: str
    status: str
    tokens_used: int
    content_preview: str


@dataclass(frozen=True, slots=True)
class EventDetail:
    event_id: int
    event_type: str
    created_at: str
    skill_name: str
    status: str
    tokens_used: int
    content: str
    payload: str


@dataclass(frozen=True, slots=True)
class DashboardSnapshot:
    summary: DashboardSummary
    skills: list[SkillPerformance]
    recent_failures: list[RecentFailure]
    token_buckets: list[TokenBucket]
    context_maps: list[ContextMapHealth]
    session_activity: list[SessionActivity]
    model_token_usage: list[ModelTokenUsage]
    session_token_usage: list[SessionTokenUsage]


@dataclass(frozen=True, slots=True)
class UnifiedEvent:
    event_id: str
    event_type: str
    timestamp: str
    session_id: str
    detail_json: str
    source_table: str


@dataclass(frozen=True, slots=True)
class ToolLatency:
    skill_name: str
    session_id: str
    latency_s: float
    status: str
    tokens_used: int


@dataclass(frozen=True, slots=True)
class SubAgentNode:
    sub_session_id: str
    parent_session_id: str
    persona: str
    objective: str
    status: str
    started_at: str
    completed_at: str
    duration_s: float
    summary: str
    # Phase 4 orchestrator extensions
    role: str = ""  # normalized role name from persona
    evaluation_score: float | None = None
    token_cost: int = 0
    conflicts: list[str] = field(default_factory=list)
    child_count: int = 0  # how many workers this node spawned


@dataclass(frozen=True, slots=True)
class ErrorSummary:
    skill_name: str
    error_count: int
    cancel_count: int
    last_error_at: str


def fetch_dashboard_snapshot(engine: Engine, *, limit: int = 12) -> DashboardSnapshot:
    return DashboardSnapshot(
        summary=fetch_summary(engine),
        skills=fetch_skill_performance(engine, limit=limit),
        recent_failures=fetch_recent_failures(engine, limit=limit),
        token_buckets=fetch_token_buckets(engine),
        context_maps=fetch_context_map_health(engine),
        session_activity=fetch_session_activity(engine, limit=limit),
        model_token_usage=fetch_model_token_usage(engine, limit=limit),
        session_token_usage=fetch_session_token_usage(engine, limit=limit),
    )


def _pending_proposal_count(engine: Engine) -> int:
    """Count pending state proposals without importing BlackboardDatabase."""
    with engine.connect() as conn:
        return (
            conn.execute(
                text("select count(*) from state_proposals where status = 'pending'")
            ).scalar_one()
            or 0
        )


def fetch_summary(engine: Engine) -> DashboardSummary:
    with engine.connect() as conn:
        row = (
            conn.execute(
                text(
                    """
                select
                    count(distinct scope_id) as total_sessions,
                    count(*) as total_events,
                    coalesce(sum(
                        case when event_type = 'LLMActionEmitted'
                        then nullif(payload->'payload'->>'tokens_used', '')::int
                        else 0 end
                    ), 0) as total_tokens,
                    count(*) filter (
                        where event_type in ('SkillCalled', 'SkillRequested')
                    ) as skill_calls,
                    count(*) filter (
                        where event_type = 'SkillCompleted'
                        and coalesce(payload->'payload'->>'status', '') not in ('', 'success')
                    ) as skill_failures
                from state_events
                """
                )
            )
            .mappings()
            .one()
        )
        pending = conn.execute(
            text("select count(*) from context_map_events where processed = 0")
        ).scalar_one()

    return DashboardSummary(
        total_sessions=int(row["total_sessions"] or 0),
        total_events=int(row["total_events"] or 0),
        total_tokens=int(row["total_tokens"] or 0),
        skill_calls=int(row["skill_calls"] or 0),
        skill_failures=int(row["skill_failures"] or 0),
        context_pending=int(pending or 0),
        pending_state_proposals=_pending_proposal_count(engine),
    )


def fetch_skill_performance(engine: Engine, *, limit: int = 12) -> list[SkillPerformance]:
    with engine.connect() as conn:
        rows = (
            conn.execute(
                text(
                    """
                    with skill_events as (
                        select
                            coalesce(
                                nullif(payload->'payload'->>'skill_name', ''),
                                nullif(payload->'payload'->>'tool_name', ''),
                                'unknown'
                            ) as skill_name,
                            coalesce(payload->'payload'->>'status', '') as status,
                            created_at,
                            row_number() over (
                                partition by coalesce(
                                    nullif(payload->'payload'->>'skill_name', ''),
                                    nullif(payload->'payload'->>'tool_name', ''),
                                    'unknown'
                                )
                                order by created_at::timestamptz desc, id desc
                            ) as recency
                        from state_events
                        where event_type = 'SkillCompleted'
                    )
                    select
                        skill_name,
                        count(*) as calls,
                        count(*) filter (where status not in ('', 'success')) as failures,
                        max(status) filter (where recency = 1) as last_status,
                        max(created_at) as last_seen
                    from skill_events
                    group by skill_name
                    order by failures desc, calls desc, skill_name asc
                    limit :limit
                    """
                ),
                {"limit": limit},
            )
            .mappings()
            .all()
        )

    return [
        SkillPerformance(
            skill_name=str(row["skill_name"]),
            calls=int(row["calls"] or 0),
            failures=int(row["failures"] or 0),
            last_status=str(row["last_status"] or ""),
            last_seen=str(row["last_seen"] or ""),
        )
        for row in rows
    ]


def fetch_recent_failures(engine: Engine, *, limit: int = 12) -> list[RecentFailure]:
    with engine.connect() as conn:
        rows = (
            conn.execute(
                text(
                    """
                    select
                        id,
                        scope_id,
                        event_type,
                        created_at,
                        coalesce(payload->'payload'->>'status', '') as status,
                        coalesce(
                            nullif(payload->'payload'->>'skill_name', ''),
                            nullif(payload->'payload'->>'tool_name', ''),
                            nullif(payload->'payload'->>'reason', ''),
                            event_type
                        ) as label,
                        coalesce(
                            nullif(payload->'payload'->>'content', ''),
                            nullif(payload->'payload'->>'result', ''),
                            nullif(payload->'payload'->>'final_answer', ''),
                            nullif(payload->'payload'->>'reasoning', ''),
                            ''
                        ) as detail
                    from state_events
                    where (
                        event_type = 'SkillCompleted'
                        and coalesce(payload->'payload'->>'status', '')
                            not in ('', 'success')
                    )
                    or event_type = 'StreamPaused'
                    or (
                        event_type = 'PipelineCompleted'
                        and coalesce(payload->'payload'->>'status', '') != 'completed'
                    )
                    order by id desc
                    limit :limit
                    """
                ),
                {"limit": limit},
            )
            .mappings()
            .all()
        )

    return [
        RecentFailure(
            event_id=int(row["id"] or 0),
            session_id=str(row["scope_id"] or ""),
            event_type=str(row["event_type"] or ""),
            status=str(row["status"] or ""),
            label=str(row["label"] or ""),
            created_at=str(row["created_at"] or ""),
            detail=str(row["detail"] or "")[:240],
        )
        for row in rows
    ]


def fetch_token_buckets(engine: Engine) -> list[TokenBucket]:
    with engine.connect() as conn:
        rows = (
            conn.execute(
                text(
                    """
                    select
                        date_trunc('hour', created_at::timestamptz) as bucket,
                        coalesce(
                            sum(nullif(payload->'payload'->>'tokens_used', '')::int),
                            0
                        ) as tokens,
                        coalesce(
                            sum(nullif(payload->'payload'->>'input_tokens', '')::int),
                            0
                        ) as input_tokens,
                        coalesce(
                            sum(nullif(payload->'payload'->>'output_tokens', '')::int),
                            0
                        ) as output_tokens
                    from state_events
                    where event_type = 'LLMActionEmitted'
                    and created_at::timestamptz >= now() - interval '48 hours'
                    group by bucket
                    order by bucket asc
                    """
                )
            )
            .mappings()
            .all()
        )

    return [
        TokenBucket(
            bucket=str(row["bucket"] or ""),
            tokens=int(row["tokens"] or 0),
            input_tokens=int(row["input_tokens"] or 0),
            output_tokens=int(row["output_tokens"] or 0),
        )
        for row in rows
    ]


def fetch_context_map_health(engine: Engine) -> list[ContextMapHealth]:
    with engine.connect() as conn:
        rows = (
            conn.execute(
                text(
                    """
                    with pending as (
                        select corpus_key, count(*) as pending_events
                        from context_map_events
                        where processed = 0
                        group by corpus_key
                    ),
                    corpus_keys as (
                        select corpus_key from context_map
                        union
                        select corpus_key from pending
                    )
                    select
                        keys.corpus_key,
                        coalesce(cm.version, 0) as version,
                        coalesce(cm.token_count, 0) as token_count,
                        coalesce(cm.last_updated, '') as last_updated,
                        coalesce(cm.freeze_until, '') as freeze_until,
                        coalesce(p.pending_events, 0) as pending_events
                    from corpus_keys keys
                    left join context_map cm on cm.corpus_key = keys.corpus_key
                    left join pending p on p.corpus_key = keys.corpus_key
                    order by pending_events desc, keys.corpus_key asc
                    """
                )
            )
            .mappings()
            .all()
        )

    return [
        ContextMapHealth(
            corpus_key=str(row["corpus_key"] or ""),
            version=int(row["version"] or 0),
            token_count=int(row["token_count"] or 0),
            last_updated=str(row["last_updated"] or ""),
            freeze_until=str(row["freeze_until"] or ""),
            pending_events=int(row["pending_events"] or 0),
        )
        for row in rows
    ]


def fetch_session_activity(engine: Engine, *, limit: int = 12) -> list[SessionActivity]:
    with engine.connect() as conn:
        rows = (
            conn.execute(
                text(
                    """
                    with ranked_events as (
                        select
                            id,
                            scope_id as session_id,
                            event_type,
                            created_at,
                            payload,
                            row_number() over (
                                partition by scope_id
                                order by created_at::timestamptz desc, id desc
                            ) as recency
                        from state_events
                        where scope = 'session'
                    ),
                    session_rollup as (
                        select
                            scope_id as session_id,
                            count(*) as event_count,
                            coalesce(sum(
                                case when event_type = 'LLMActionEmitted'
                                then nullif(payload->'payload'->>'tokens_used', '')::int
                                else 0 end
                            ), 0) as total_tokens,
                            count(*) filter (
                                where event_type = 'SkillCompleted'
                                and coalesce(payload->'payload'->>'status', '')
                                    not in ('', 'success')
                            ) as skill_failures,
                            coalesce(
                                max(payload->'payload'->>'goal') filter (
                                    where event_type = 'AgentStarted'
                                ),
                                ''
                            ) as goal
                        from state_events
                        where scope = 'session'
                        group by scope_id
                    )
                    select
                        rollup.session_id,
                        case
                            when latest.event_type = 'StreamPaused' then 'paused'
                            else 'active'
                        end as status,
                        latest.event_type as last_event_type,
                        rollup.event_count,
                        rollup.total_tokens,
                        rollup.skill_failures,
                        latest.created_at as last_seen,
                        rollup.goal
                    from session_rollup rollup
                    join ranked_events latest
                        on latest.session_id = rollup.session_id
                        and latest.recency = 1
                    order by latest.created_at::timestamptz desc, latest.id desc
                    limit :limit
                    """
                ),
                {"limit": limit},
            )
            .mappings()
            .all()
        )

    return [
        SessionActivity(
            session_id=str(row["session_id"] or ""),
            status=str(row["status"] or ""),
            last_event_type=str(row["last_event_type"] or ""),
            event_count=int(row["event_count"] or 0),
            total_tokens=int(row["total_tokens"] or 0),
            skill_failures=int(row["skill_failures"] or 0),
            last_seen=str(row["last_seen"] or ""),
            goal=str(row["goal"] or "")[:180],
        )
        for row in rows
    ]


def fetch_model_token_usage(engine: Engine, *, limit: int = 12) -> list[ModelTokenUsage]:
    with engine.connect() as conn:
        rows = (
            conn.execute(
                text(
                    """
                    select
                        coalesce(nullif(payload->'payload'->>'model', ''), 'unknown') as model,
                        count(*) as actions,
                        count(distinct scope_id) as sessions,
                        coalesce(sum(nullif(payload->'payload'->>'tokens_used', '')::int), 0)
                            as tokens,
                        coalesce(sum(nullif(payload->'payload'->>'input_tokens', '')::int), 0)
                            as input_tokens,
                        coalesce(sum(nullif(payload->'payload'->>'output_tokens', '')::int), 0)
                            as output_tokens,
                        coalesce(sum(nullif(payload->'payload'->>'billable_tokens', '')::int), 0)
                            as billable_tokens,
                        coalesce(sum(nullif(payload->'payload'->>'new_tokens', '')::int), 0)
                            as new_tokens
                    from state_events
                    where event_type = 'LLMActionEmitted'
                    group by model
                    order by tokens desc, model asc
                    limit :limit
                    """
                ),
                {"limit": limit},
            )
            .mappings()
            .all()
        )

    return [
        ModelTokenUsage(
            model=str(row["model"] or ""),
            actions=int(row["actions"] or 0),
            sessions=int(row["sessions"] or 0),
            tokens=int(row["tokens"] or 0),
            input_tokens=int(row["input_tokens"] or 0),
            output_tokens=int(row["output_tokens"] or 0),
            billable_tokens=int(row["billable_tokens"] or 0),
            new_tokens=int(row["new_tokens"] or 0),
        )
        for row in rows
    ]


def fetch_session_token_usage(engine: Engine, *, limit: int = 12) -> list[SessionTokenUsage]:
    with engine.connect() as conn:
        rows = (
            conn.execute(
                text(
                    """
                    select
                        scope_id as session_id,
                        string_agg(
                            distinct coalesce(nullif(payload->'payload'->>'model', ''), 'unknown'),
                            ', '
                        ) as models,
                        count(*) as actions,
                        coalesce(sum(nullif(payload->'payload'->>'tokens_used', '')::int), 0)
                            as tokens,
                        coalesce(sum(nullif(payload->'payload'->>'input_tokens', '')::int), 0)
                            as input_tokens,
                        coalesce(sum(nullif(payload->'payload'->>'output_tokens', '')::int), 0)
                            as output_tokens,
                        coalesce(sum(nullif(payload->'payload'->>'billable_tokens', '')::int), 0)
                            as billable_tokens,
                        coalesce(sum(nullif(payload->'payload'->>'new_tokens', '')::int), 0)
                            as new_tokens,
                        max(created_at) as last_seen
                    from state_events
                    where event_type = 'LLMActionEmitted'
                    group by scope_id
                    order by tokens desc, scope_id asc
                    limit :limit
                    """
                ),
                {"limit": limit},
            )
            .mappings()
            .all()
        )

    return [
        SessionTokenUsage(
            session_id=str(row["session_id"] or ""),
            models=str(row["models"] or ""),
            actions=int(row["actions"] or 0),
            tokens=int(row["tokens"] or 0),
            input_tokens=int(row["input_tokens"] or 0),
            output_tokens=int(row["output_tokens"] or 0),
            billable_tokens=int(row["billable_tokens"] or 0),
            new_tokens=int(row["new_tokens"] or 0),
            last_seen=str(row["last_seen"] or ""),
        )
        for row in rows
    ]


def snapshot_to_dict(snapshot: DashboardSnapshot) -> dict[str, Any]:
    return {
        "summary": asdict(snapshot.summary),
        "skills": [asdict(row) for row in snapshot.skills],
        "recent_failures": [asdict(row) for row in snapshot.recent_failures],
        "token_buckets": [asdict(row) for row in snapshot.token_buckets],
        "context_maps": [asdict(row) for row in snapshot.context_maps],
        "session_activity": [asdict(row) for row in snapshot.session_activity],
        "model_token_usage": [asdict(row) for row in snapshot.model_token_usage],
        "session_token_usage": [asdict(row) for row in snapshot.session_token_usage],
    }


def fetch_session_ids(engine: Engine, *, limit: int = 50) -> list[tuple[str, str]]:
    """Return (session_id, display_label) pairs.

    Ordered most-recent-first. Queries the sessions table as the canonical
    source so sessions without events are still visible.
    """
    with engine.connect() as conn:
        rows = (
            conn.execute(
                text(
                    """
                    select
                        s.session_id,
                        s.global_objective,
                        s.created_at,
                        coalesce(
                            max(payload->'payload'->>'goal')
                                filter (where se.event_type = 'AgentStarted'),
                            ''
                        ) as goal,
                        max(se.created_at) as last_event_at
                    from sessions s
                    left join state_events se
                        on se.scope_id = s.session_id
                        and se.scope = 'session'
                    group by s.session_id, s.global_objective, s.created_at
                    order by coalesce(max(se.created_at), s.created_at) desc
                    limit :limit
                    """
                ),
                {"limit": limit},
            )
            .mappings()
            .all()
        )
    return [
        (
            str(row["session_id"]),
            f"{str(row['goal'] or row['global_objective'])[:60] or '—'}  [{str(row['session_id'])[-8:]}]",
        )
        for row in rows
    ]


def fetch_session_events(engine: Engine, session_id: str) -> list[SessionEventRow]:
    """Return all events for *session_id* ordered by time, with a time_delta field."""
    with engine.connect() as conn:
        rows = (
            conn.execute(
                text(
                    """
                    select
                        id,
                        event_type,
                        created_at,
                        coalesce(
                            nullif(payload->'payload'->>'skill_name', ''),
                            nullif(payload->'payload'->>'tool_name', ''),
                            ''
                        ) as skill_name,
                        coalesce(payload->'payload'->>'status', '') as status,
                        coalesce(
                            nullif(payload->'payload'->>'tokens_used', '')::int,
                            0
                        ) as tokens_used,
                        coalesce(
                            nullif(payload->'payload'->>'content', ''),
                            nullif(payload->'payload'->>'result', ''),
                            nullif(payload->'payload'->>'goal', ''),
                            nullif(payload->'payload'->>'reason', ''),
                            nullif(payload->'payload'->>'user_content', ''),
                            nullif(payload->'payload'->>'reasoning', ''),
                            nullif(payload->'payload'->>'final_answer', ''),
                            payload->'payload'->>'arguments',
                            ''
                        ) as content
                    from state_events
                    where scope_id = :session_id
                    order by created_at asc, id asc
                    """
                ),
                {"session_id": session_id},
            )
            .mappings()
            .all()
        )

    if not rows:
        return []

    from datetime import datetime  # noqa: PLC0415

    def _parse_ts(s: str) -> datetime | None:
        try:
            return datetime.fromisoformat(s)
        except ValueError:
            return None

    first_ts = _parse_ts(str(rows[0]["created_at"]))
    result: list[SessionEventRow] = []
    for row in rows:
        ts = _parse_ts(str(row["created_at"]))
        delta = round((ts - first_ts).total_seconds(), 1) if ts and first_ts else 0.0
        raw_content = str(row["content"] or "")
        result.append(
            SessionEventRow(
                event_id=int(row["id"]),
                event_type=str(row["event_type"]),
                created_at=str(row["created_at"]),
                time_delta=delta,
                skill_name=str(row["skill_name"] or ""),
                status=str(row["status"] or ""),
                tokens_used=int(row["tokens_used"] or 0),
                content_preview=raw_content[:_CONTENT_PREVIEW_CHARS],
            )
        )
    return result


def fetch_event_detail(engine: Engine, event_id: int) -> EventDetail | None:
    """Return full detail for a single event, including the un-truncated content."""
    with engine.connect() as conn:
        row = (
            conn.execute(
                text(
                    """
                    select
                        id,
                        event_type,
                        created_at,
                        coalesce(
                            nullif(payload->'payload'->>'skill_name', ''),
                            nullif(payload->'payload'->>'tool_name', ''),
                            ''
                        ) as skill_name,
                        coalesce(payload->'payload'->>'status', '') as status,
                        coalesce(
                            nullif(payload->'payload'->>'tokens_used', '')::int,
                            0
                        ) as tokens_used,
                        coalesce(
                            nullif(payload->'payload'->>'content', ''),
                            nullif(payload->'payload'->>'result', ''),
                            nullif(payload->'payload'->>'goal', ''),
                            nullif(payload->'payload'->>'reason', ''),
                            nullif(payload->'payload'->>'user_content', ''),
                            nullif(payload->'payload'->>'reasoning', ''),
                            nullif(payload->'payload'->>'final_answer', ''),
                            payload->'payload'->>'arguments',
                            ''
                        ) as content,
                        payload::text as raw_payload
                    from state_events
                    where id = :event_id
                    """
                ),
                {"event_id": event_id},
            )
            .mappings()
            .one_or_none()
        )
    if row is None:
        return None
    return EventDetail(
        event_id=int(row["id"]),
        event_type=str(row["event_type"]),
        created_at=str(row["created_at"]),
        skill_name=str(row["skill_name"] or ""),
        status=str(row["status"] or ""),
        tokens_used=int(row["tokens_used"] or 0),
        content=str(row["content"] or ""),
        payload=str(row["raw_payload"] or "{}"),
    )


def fetch_corpus_keys(engine: Engine) -> list[str]:
    """Return distinct corpus_keys that have a stored context map."""
    with engine.connect() as conn:
        rows = conn.execute(
            text("select distinct corpus_key from context_map order by corpus_key")
        ).all()
    return [str(row[0]) for row in rows]


def fetch_context_map_entries(engine: Engine, corpus_key: str) -> list[ContextMapEntrySummary]:
    """Return entry summaries for a given corpus_key.

    Reads the serialised map_json blob and deserialises it into
    lightweight dashboard-friendly rows.  Returns an empty list when
    the corpus_key is unknown or the stored JSON is unparseable.
    """
    with engine.connect() as conn:
        row = conn.execute(
            text("select map_json, schema_version from context_map where corpus_key = :key"),
            {"key": corpus_key},
        ).one_or_none()

    if row is None:
        _log.warning("fetch_context_map_entries: no row for corpus_key=%r", corpus_key)
        return []

    try:
        raw = json.loads(row[0])
    except json.JSONDecodeError:
        _log.exception("fetch_context_map_entries: invalid JSON for corpus_key=%r", corpus_key)
        return []

    schema_version = row[1] or 1
    if schema_version == 1:
        _log.info("fetch_context_map_entries: legacy schema_version=1, translating")
        if not isinstance(raw, dict):
            _log.warning(
                "fetch_context_map_entries: expected dict for v1, got %s",
                type(raw).__name__,
            )
            return []
        from harness_poc.core.storage.database import _legacy_to_entries  # noqa: PLC0415

        entries = _legacy_to_entries(raw, corpus_key)
        return [
            ContextMapEntrySummary(
                entry_id=e.entry_id,
                key=e.key,
                section=e.section,
                observation_type=e.observation_type,
                priority=e.priority,
                materialization_count=e.materialization_count,
                token_estimate=e.token_estimate,
                summary=e.summary,
            )
            for e in entries
        ]

    if not isinstance(raw, list):
        _log.warning(
            "fetch_context_map_entries: expected list, got %s for corpus_key=%r",
            type(raw).__name__,
            corpus_key,
        )
        return []

    _log.info("fetch_context_map_entries: %d raw entries for corpus_key=%r", len(raw), corpus_key)

    summaries: list[ContextMapEntrySummary] = []
    for entry_dict in raw:
        try:
            e = MapEntry.model_validate(entry_dict)
        except ValidationError:
            _log.exception(
                "fetch_context_map_entries: validation failed for entry key=%r",
                entry_dict.get("key", "?"),
            )
            continue
        summaries.append(
            ContextMapEntrySummary(
                entry_id=e.entry_id,
                key=e.key,
                section=e.section,
                observation_type=e.observation_type,
                priority=e.priority,
                materialization_count=e.materialization_count,
                token_estimate=e.token_estimate,
                summary=e.summary,
            )
        )

    _log.info(
        "fetch_context_map_entries: %d validated entries for corpus_key=%r",
        len(summaries),
        corpus_key,
    )
    return summaries


def fetch_recent_events(
    engine: Engine,
    *,
    limit: int = 200,
    session_id: str | None = None,
    event_types: list[str] | None = None,
) -> list[UnifiedEvent]:
    """Return recent events from state_events and context_map_events.

    UNION ALL across the two tables so the dashboard has a single
    unified timeline.  Optional *session_id* and *event_types*
    filters apply to both halves independently then merged.
    """
    se_conds: list[str] = []
    cme_conds: list[str] = []
    params: dict[str, Any] = {"limit": limit}

    if session_id is not None:
        se_conds.append("scope_id = :session_id")
        cme_conds.append("session_id = :session_id")
        params["session_id"] = session_id

    if event_types:
        se_conds.append("event_type = ANY(:event_types)")
        cme_conds.append("event_type = ANY(:event_types)")
        params["event_types"] = event_types

    se_where = (" where " + " and ".join(se_conds)) if se_conds else ""
    cme_where = (" where " + " and ".join(cme_conds)) if cme_conds else ""

    sql = text(
        f"select * from ("  # noqa: S608
        f"  select id::text as event_id, event_type, created_at as timestamp,"
        f"         scope_id as session_id,"
        f"         coalesce(payload->'payload', '{{}}'::jsonb)::text as detail_json,"
        f"         'state_events' as source_table"
        f"  from state_events"
        f"  {se_where}"
        f"  union all"
        f"  select event_id, event_type, timestamp, session_id,"
        f"         payload as detail_json, 'context_map_events' as source_table"
        f"  from context_map_events"
        f"  {cme_where}"
        f") combined"
        f" order by timestamp desc"
        f" limit :limit"
    )

    with engine.connect() as conn:
        rows = conn.execute(sql, params).mappings().all()

    return [
        UnifiedEvent(
            event_id=str(row["event_id"] or ""),
            event_type=str(row["event_type"] or ""),
            timestamp=str(row["timestamp"] or ""),
            session_id=str(row["session_id"] or ""),
            detail_json=str(row["detail_json"] or "{}"),
            source_table=str(row["source_table"] or ""),
        )
        for row in rows
    ]


def fetch_tool_latency(
    engine: Engine,
    *,
    minutes: int = 60,
) -> list[ToolLatency]:
    """Match SkillCalled → SkillCompleted pairs to compute latency.

    Pairs are matched on (session_id, skill_name) where the
    SkillCompleted occurs within 300 seconds of the SkillCalled.
    Only SkillCalled events in the last *minutes* minutes are
    considered.
    """
    with engine.connect() as conn:
        rows = (
            conn.execute(
                text(
                    """
                    with called as (
                        select
                            coalesce(
                                nullif(payload->'payload'->>'skill_name', ''),
                                nullif(payload->'payload'->>'tool_name', ''),
                                'unknown'
                            ) as skill_name,
                            scope_id as session_id,
                            created_at
                        from state_events
                        where event_type = 'SkillCalled'
                          and created_at::timestamptz
                              > now() - (:minutes || ' minutes')::interval
                    ),
                    completed as (
                        select
                            coalesce(
                                nullif(payload->'payload'->>'skill_name', ''),
                                nullif(payload->'payload'->>'tool_name', ''),
                                'unknown'
                            ) as skill_name,
                            scope_id as session_id,
                            created_at,
                            coalesce(payload->'payload'->>'status', '') as status,
                            coalesce(
                                nullif(payload->'payload'->>'tokens_used', '')::int, 0
                            ) as tokens_used
                        from state_events
                        where event_type = 'SkillCompleted'
                    )
                    select
                        c.skill_name,
                        c.session_id,
                        extract(epoch from (
                            comp.created_at::timestamptz - c.created_at::timestamptz
                        )) as latency_s,
                        comp.status,
                        comp.tokens_used
                    from called c
                    join lateral (
                        select * from completed comp
                        where comp.skill_name = c.skill_name
                          and comp.session_id = c.session_id
                          and comp.created_at::timestamptz
                              > c.created_at::timestamptz
                          and comp.created_at::timestamptz
                              <= c.created_at::timestamptz + interval '300 seconds'
                        order by comp.created_at asc
                        limit 1
                    ) comp on true
                    order by c.created_at desc
                    """
                ),
                {"minutes": str(minutes)},
            )
            .mappings()
            .all()
        )

    return [
        ToolLatency(
            skill_name=str(row["skill_name"] or ""),
            session_id=str(row["session_id"] or ""),
            latency_s=float(row["latency_s"] or 0.0),
            status=str(row["status"] or ""),
            tokens_used=int(row["tokens_used"] or 0),
        )
        for row in rows
    ]


def _compute_duration(started_at: str, completed_at: str) -> float:
    """Compute duration in seconds between two ISO timestamps.

    Returns 0.0 if either timestamp is missing or unparseable.
    """
    if not started_at or not completed_at:
        return 0.0
    from datetime import datetime  # noqa: PLC0415

    try:
        start = datetime.fromisoformat(started_at)
        end = datetime.fromisoformat(completed_at)
        return round((end - start).total_seconds(), 1)
    except ValueError:
        return 0.0


def _normalize_role(persona: str) -> str:
    """Extract a clean role name from persona identifiers.

    Personas can be full paths (agents/roles/code_reviewer), skill names,
    or bare role names. This strips common prefixes/suffixes.
    """
    if not persona:
        return ""
    # Strip path prefixes
    for prefix in ("agents/roles/", "personas/", "skills/", "system_skills/"):
        persona = persona.removeprefix(prefix)
    # Strip file extensions
    for ext in (".md", ".yaml", ".yml"):
        persona = persona.removesuffix(ext)
    return persona


def fetch_sub_agent_tree(engine: Engine) -> list[SubAgentNode]:
    """Return sub-agent dispatch/completion tree from both event stores.

    Merges entries from state_events (SubAgentDispatched /
    SubAgentCompleted) with context_map_events (SubAgentTaskStarted /
    SubAgentTaskCompleted).  Deduplicates on *sub_session_id*,
    preferring the state_events entry when both exist.
    """
    nodes: dict[str, SubAgentNode] = {}

    with engine.connect() as conn:
        # ── state_events (Approach A) ──────────────────────────
        se_rows = (
            conn.execute(
                text(
                    """
                    select
                        d.scope_id as parent_session_id,
                        d.payload->'payload'->>'sub_session_id' as sub_session_id,
                        d.payload->'payload'->>'persona' as persona,
                        d.payload->'payload'->>'objective' as objective,
                        coalesce(
                            c.payload->'payload'->>'status', 'dispatched'
                        ) as status,
                        d.created_at as started_at,
                        c.created_at as completed_at,
                        coalesce(
                            c.payload->'payload'->>'content', ''
                        ) as summary
                    from state_events d
                    left join state_events c
                        on c.event_type = 'SubAgentCompleted'
                        and c.payload->'payload'->>'sub_session_id'
                            = d.payload->'payload'->>'sub_session_id'
                        and c.scope_id = d.scope_id
                    where d.event_type = 'SubAgentDispatched'
                    order by d.created_at desc
                    """
                )
            )
            .mappings()
            .all()
        )

        for row in se_rows:
            sub_id = str(row["sub_session_id"] or "")
            if not sub_id:
                continue
            started = str(row["started_at"] or "")
            completed = str(row["completed_at"] or "")
            nodes[sub_id] = SubAgentNode(
                sub_session_id=sub_id,
                parent_session_id=str(row["parent_session_id"] or ""),
                persona=str(row["persona"] or ""),
                objective=str(row["objective"] or ""),
                status=str(row["status"] or ""),
                started_at=started,
                completed_at=completed,
                duration_s=_compute_duration(started, completed),
                summary=str(row["summary"] or ""),
                role=_normalize_role(str(row["persona"] or "")),
            )

        # ── context_map_events (Approach B) ────────────────────
        cme_rows = (
            conn.execute(
                text(
                    """
                    select
                        s.session_id as parent_session_id,
                        s.payload::json->>'sub_session_id' as sub_session_id,
                        s.payload::json->>'persona' as persona,
                        s.payload::json->>'objective' as objective,
                        coalesce(
                            c.payload::json->>'status', 'started'
                        ) as status,
                        s.timestamp as started_at,
                        c.timestamp as completed_at,
                        coalesce(
                            c.payload::json->>'summary', ''
                        ) as summary
                    from context_map_events s
                    left join context_map_events c
                        on c.event_type = 'SubAgentTaskCompleted'
                        and c.payload::json->>'task_id'
                            = s.payload::json->>'sub_session_id'
                        and c.session_id = s.session_id
                    where s.event_type = 'SubAgentTaskStarted'
                    order by s.timestamp desc
                    """
                )
            )
            .mappings()
            .all()
        )

        for row in cme_rows:
            sub_id = str(row["sub_session_id"] or "")
            if not sub_id or sub_id in nodes:
                continue  # prefer state_events entry
            started = str(row["started_at"] or "")
            nodes[sub_id] = SubAgentNode(
                sub_session_id=sub_id,
                parent_session_id=str(row["parent_session_id"] or ""),
                persona=str(row["persona"] or ""),
                objective=str(row["objective"] or ""),
                status=str(row["status"] or ""),
                started_at=started,
                completed_at=completed,
                duration_s=_compute_duration(started, completed),
                summary=str(row["summary"] or ""),
                role=_normalize_role(str(row["persona"] or "")),
            )

    # Compute child counts for orchestrator tree visualization
    for node in nodes.values():
        child_count = sum(
            1 for other in nodes.values() if other.parent_session_id == node.sub_session_id
        )
        if child_count > 0:
            nodes[node.sub_session_id] = SubAgentNode(
                sub_session_id=node.sub_session_id,
                parent_session_id=node.parent_session_id,
                persona=node.persona,
                objective=node.objective,
                status=node.status,
                started_at=node.started_at,
                completed_at=node.completed_at,
                duration_s=node.duration_s,
                summary=node.summary,
                role=node.role,
                child_count=child_count,
            )

    return list(nodes.values())


def fetch_event_throughput(engine: Engine, *, window_s: int = 60) -> float:
    """Return events/second over the last *window_s* seconds."""
    with engine.connect() as conn:
        state_count = conn.execute(
            text(
                "select count(*) from state_events "
                "where created_at::timestamptz > now() - (:window || ' seconds')::interval"
            ),
            {"window": str(window_s)},
        ).scalar_one()

        cme_count = conn.execute(
            text(
                "select count(*) from context_map_events "
                "where timestamp::timestamptz > now() - (:window || ' seconds')::interval"
            ),
            {"window": str(window_s)},
        ).scalar_one()

    total = int(state_count or 0) + int(cme_count or 0)
    return round(total / window_s, 2) if window_s > 0 else 0.0


def fetch_error_summary(engine: Engine, *, hours: int = 24) -> list[ErrorSummary]:
    """Return error/cancel counts grouped by skill_name.

    Aggregates SkillCompleted rows with status in ('failed','error')
    and SkillCancelled rows, all within the last *hours* hours.
    """
    with engine.connect() as conn:
        rows = (
            conn.execute(
                text(
                    """
                    with skill_name_extracted as (
                        select
                            coalesce(
                                nullif(payload->'payload'->>'skill_name', ''),
                                nullif(payload->'payload'->>'tool_name', ''),
                                'unknown'
                            ) as skill_name,
                            coalesce(payload->'payload'->>'status', '') as status,
                            event_type,
                            created_at
                        from state_events
                        where created_at::timestamptz
                              > now() - (:hours || ' hours')::interval
                          and event_type in (
                              'SkillCompleted', 'SkillCancelled'
                          )
                    )
                    select
                        skill_name,
                        coalesce(count(*) filter (
                            where event_type = 'SkillCompleted'
                              and status in ('failed', 'error')
                        ), 0) as error_count,
                        coalesce(count(*) filter (
                            where event_type = 'SkillCancelled'
                        ), 0) as cancel_count,
                        max(created_at) filter (
                            where event_type = 'SkillCompleted'
                              and status in ('failed', 'error')
                        ) as last_error_at
                    from skill_name_extracted
                    group by skill_name
                    having coalesce(count(*) filter (
                               where event_type = 'SkillCompleted'
                                 and status in ('failed', 'error')
                           ), 0) > 0
                        or coalesce(count(*) filter (
                               where event_type = 'SkillCancelled'
                           ), 0) > 0
                    order by error_count desc, cancel_count desc, skill_name asc
                    """
                ),
                {"hours": str(hours)},
            )
            .mappings()
            .all()
        )

    return [
        ErrorSummary(
            skill_name=str(row["skill_name"] or ""),
            error_count=int(row["error_count"] or 0),
            cancel_count=int(row["cancel_count"] or 0),
            last_error_at=str(row["last_error_at"] or ""),
        )
        for row in rows
    ]


# ── Skill Compilation (dashboard skills view) ──────────────────────────


_BUNDLE_JSON_FILENAME = ".skill_bundle.json"


@dataclass(frozen=True, slots=True)
class SkillContractSummary:
    name: str
    description: str
    input_count: int
    output_count: int
    precondition_count: int
    error_condition_count: int
    cancellation_behavior: str


@dataclass(frozen=True, slots=True)
class SkillTemplateSummary:
    name: str
    kind: str
    template_preview: str


@dataclass(frozen=True, slots=True)
class SkillCompilationSummary:
    name: str
    skill_type: str
    version: str
    compilation_status: str
    contract_count: int
    template_count: int
    invoke_pattern_count: int
    error_count: int
    compiled_at: str
    contracts: list[SkillContractSummary] = field(default_factory=list)
    templates: list[SkillTemplateSummary] = field(default_factory=list)
    compilation_errors: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class CompilationProgress:
    running: bool
    total: int
    completed: int
    errors: int


def _read_frontmatter_name_type(skill_md: Path) -> tuple[str, str, str, list[str]] | None:
    """Extract (name, skill_type, version, aliases) from a SKILL.md frontmatter."""
    try:
        text = skill_md.read_text(encoding="utf-8")
    except OSError:
        return None
    if not text.startswith("---"):
        return None
    fm_end = text.find("\n---", 3)
    if fm_end == -1:
        return None
    try:
        fm = yaml.safe_load(text[3:fm_end])
    except yaml.YAMLError:
        return None
    if not isinstance(fm, dict):
        return None
    name = str(fm.get("name", skill_md.parent.name))
    skill_type = str(fm.get("type", "unknown"))
    version = str(fm.get("version", ""))
    raw_aliases = fm.get("aliases", [])
    aliases = list(raw_aliases) if isinstance(raw_aliases, list) else []
    return name, skill_type, version, aliases


def _read_bundle_json(skill_dir: Path) -> dict[str, Any] | None:
    """Read a persisted bundle JSON, returning None if absent or corrupt."""
    bundle_path = skill_dir / _BUNDLE_JSON_FILENAME
    if not bundle_path.exists():
        return None
    try:
        return json.loads(bundle_path.read_text(encoding="utf-8"))
    except OSError, json.JSONDecodeError:
        return None


def _build_contract_summaries(bundle: dict[str, Any]) -> list[SkillContractSummary]:
    return [
        SkillContractSummary(
            name=str(cdata.get("name", "")),
            description=str(cdata.get("description", "")),
            input_count=len(cdata.get("inputs", {})),
            output_count=len(cdata.get("outputs", {})),
            precondition_count=len(cdata.get("preconditions", [])),
            error_condition_count=len(cdata.get("error_conditions", [])),
            cancellation_behavior=str(cdata.get("cancellation_behavior", "unknown")),
        )
        for cdata in bundle.get("contracts", {}).values()
    ]


def _build_template_summaries(bundle: dict[str, Any]) -> list[SkillTemplateSummary]:
    templates: list[SkillTemplateSummary] = []
    for tname, tdata in bundle.get("templates", {}).items():
        raw_tmpl = str(tdata.get("template", ""))
        templates.append(
            SkillTemplateSummary(
                name=tname,
                kind=str(tdata.get("kind", "unknown")),
                template_preview=raw_tmpl[:120],
            )
        )
    return templates


def fetch_skill_compilation_summaries(
    skills_dirs: list[Path],
) -> list[SkillCompilationSummary]:
    """Return compilation summaries for all discovered skills."""
    summaries: list[SkillCompilationSummary] = []
    seen: set[str] = set()
    for d in skills_dirs:
        if not d.exists():
            continue
        for skill_md in sorted(d.glob("*/SKILL.md")):
            fm = _read_frontmatter_name_type(skill_md)
            if fm is None:
                continue
            name, skill_type, version, aliases = fm
            if name in seen:
                continue
            seen.add(name)

            bundle = _read_bundle_json(skill_md.parent)
            if bundle is None:
                summaries.append(
                    SkillCompilationSummary(
                        name=name,
                        skill_type=skill_type,
                        version=version,
                        compilation_status="not_compiled",
                        contract_count=0,
                        template_count=0,
                        invoke_pattern_count=0,
                        error_count=0,
                        compiled_at="",
                        aliases=aliases,
                    )
                )
                continue

            compiled_ts = bundle.get("compiled_at", 0.0)
            if isinstance(compiled_ts, (int, float)) and compiled_ts > 0:
                compiled_str = datetime.fromtimestamp(float(compiled_ts), tz=UTC).isoformat()
            else:
                compiled_str = ""

            summaries.append(
                SkillCompilationSummary(
                    name=name,
                    skill_type=skill_type,
                    version=version,
                    compilation_status=str(bundle.get("compilation_status", "rejected")),
                    contract_count=bundle.get("contract_count", 0)
                    or len(bundle.get("contracts", {})),
                    template_count=bundle.get("template_count", 0)
                    or len(bundle.get("templates", {})),
                    invoke_pattern_count=len(bundle.get("invoke_patterns", [])),
                    error_count=len(bundle.get("compilation_errors", [])),
                    compiled_at=compiled_str,
                    contracts=_build_contract_summaries(bundle),
                    templates=_build_template_summaries(bundle),
                    compilation_errors=[str(e) for e in bundle.get("compilation_errors", [])],
                    aliases=aliases,
                )
            )

    summaries.sort(key=lambda s: s.name)
    return summaries
