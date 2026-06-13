from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError
from sqlalchemy import text

from harness_poc.core.context_map.schema import MapEntry

if TYPE_CHECKING:
    from sqlalchemy import Engine

_log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DashboardSummary:
    total_sessions: int
    total_events: int
    total_tokens: int
    skill_calls: int
    skill_failures: int
    context_pending: int


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
class DashboardSnapshot:
    summary: DashboardSummary
    skills: list[SkillPerformance]
    recent_failures: list[RecentFailure]
    token_buckets: list[TokenBucket]
    context_maps: list[ContextMapHealth]
    session_activity: list[SessionActivity]
    model_token_usage: list[ModelTokenUsage]
    session_token_usage: list[SessionTokenUsage]


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


def fetch_summary(engine: Engine) -> DashboardSummary:
    with engine.connect() as conn:
        row = conn.execute(
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
        ).mappings().one()
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
        result.append(
            SessionEventRow(
                event_id=int(row["id"]),
                event_type=str(row["event_type"]),
                created_at=str(row["created_at"]),
                time_delta=delta,
                skill_name=str(row["skill_name"] or ""),
                status=str(row["status"] or ""),
                tokens_used=int(row["tokens_used"] or 0),
                content_preview=str(row["content"] or "")[:120],
            )
        )
    return result


def fetch_corpus_keys(engine: Engine) -> list[str]:
    """Return distinct corpus_keys that have a stored context map."""
    with engine.connect() as conn:
        rows = conn.execute(
            text("select distinct corpus_key from context_map order by corpus_key")
        ).all()
    return [str(row[0]) for row in rows]


def fetch_context_map_entries(
    engine: Engine, corpus_key: str
) -> list[ContextMapEntrySummary]:
    """Return entry summaries for a given corpus_key.

    Reads the serialised map_json blob and deserialises it into
    lightweight dashboard-friendly rows.  Returns an empty list when
    the corpus_key is unknown or the stored JSON is unparseable.
    """
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "select map_json, schema_version from context_map "
                "where corpus_key = :key"
            ),
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
