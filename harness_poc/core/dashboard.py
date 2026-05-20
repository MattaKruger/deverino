from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy import Engine


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
