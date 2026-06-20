from __future__ import annotations

import asyncio
import dataclasses
import json

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from harness_poc.core.observability.dashboard import (
    CompilationProgress,
    ContextMapEntrySummary,
    ContextMapHealth,
    DashboardSnapshot,
    ErrorSummary,
    EventDetail,
    SessionActivity,
    SessionEventRow,
    SkillCompilationSummary,
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
    fetch_skill_compilation_summaries,
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


@router.get("/api/skills")
def get_skills(request: Request) -> list[SkillCompilationSummary]:  # noqa: ARG001
    from pathlib import Path  # noqa: PLC0415

    from harness_poc.core.config import HarnessConfig  # noqa: PLC0415

    config = HarnessConfig.load()
    skills_dirs = [config.paths.project_skills]
    if config.paths.system_skills.exists():
        skills_dirs.append(config.paths.system_skills)
    return fetch_skill_compilation_summaries([Path(d) for d in skills_dirs])


@router.get("/api/skills/progress")
def get_skills_progress(request: Request) -> CompilationProgress:  # noqa: ARG001
    from harness_poc.core.skills.skill_compiler import (  # noqa: PLC0415
        get_compilation_status,
    )

    status = get_compilation_status()
    return CompilationProgress(
        running=bool(status.get("running", False)),
        total=int(status.get("total", 0)),
        completed=int(status.get("completed", 0)),
        errors=int(status.get("errors", 0)),
    )


@router.post("/api/skills/compile")
def post_compile_skills(request: Request) -> dict[str, str]:
    """Trigger background compilation of all skills."""
    import threading  # noqa: PLC0415
    from pathlib import Path  # noqa: PLC0415, TC003

    from harness_poc.core.config import HarnessConfig  # noqa: PLC0415
    from harness_poc.core.skills.skill_compiler import (  # noqa: PLC0415
        _build_skill_compiled_event,
        _rejected_bundle,
        compile_skill,
        get_compilation_status,
        publish_compile_event,
        set_compilation_progress,
    )
    from harness_poc.core.skills.skill_runner import SkillRunner  # noqa: PLC0415
    from harness_poc.core.storage import (  # noqa: PLC0415
        BlackboardDatabase,
        create_db_engine,
    )

    # Use set_compilation_progress as atomic check-and-set to prevent
    # dual compilation from concurrent POST requests.
    status = get_compilation_status()
    if status.get("running"):
        return {"status": "already_running"}

    model = request.app.state.compiler_model
    if model is None:
        return {
            "status": "error",
            "detail": "LLM model not available — check API keys and provider configuration",
        }

    config = HarnessConfig.load()
    knowledge_dirs = [config.paths.project_skills]
    if config.paths.system_skills.exists():
        knowledge_dirs.append(config.paths.system_skills)

    skill_files: list[Path] = []
    for d in knowledge_dirs:
        if not d.exists():
            continue
        skill_files.extend(sorted(d.glob("*/SKILL.md")))

    if not skill_files:
        return {"status": "no_skills_found"}

    # Mark running before spawning the thread — the thread's finally block
    # will set running=False.
    set_compilation_progress(running=True)

    def _compile_all() -> None:
        import time  # noqa: PLC0415

        db = BlackboardDatabase(create_db_engine(config.runtime.database_url))
        runner = SkillRunner(database=db, config=config)
        total = len(skill_files)
        set_compilation_progress(total=total, running=True)
        completed = 0
        errors = 0
        # Emit initial progress so the frontend shows total immediately
        publish_compile_event({
            "event": "compilation_progress",
            "total": total,
            "completed": 0,
            "errors": 0,
            "running": True,
        })
        try:
            for sf in skill_files:
                skill_name = sf.parent.name
                try:
                    bundle = compile_skill(
                        sf,
                        skill_runner=runner,
                        force=True,
                        model=model,
                        compiler_config=config.compiler,
                    )
                    completed += 1
                except Exception as exc:
                    errors += 1
                    # Emit a rejected event so the frontend updates the card
                    bundle = _rejected_bundle(sf, [str(exc)])
                    bundle.compiled_at = time.time()
                    completed += 1  # count as completed (rejected) not crashed
                # Per-skill event
                publish_compile_event(_build_skill_compiled_event(skill_name, bundle))
                # Progress update
                publish_compile_event(
                    {
                        "event": "compilation_progress",
                        "total": total,
                        "completed": completed,
                        "errors": errors,
                        "running": True,
                    }
                )
                set_compilation_progress(total=total, completed=completed, errors=errors)
        finally:
            set_compilation_progress(running=False)
            publish_compile_event(
                {
                    "event": "compilation_done",
                    "total": total,
                    "completed": completed,
                    "errors": errors,
                }
            )

    threading.Thread(target=_compile_all, daemon=True).start()
    return {"status": "started"}


@router.post("/api/skills/{name}/compile")
def post_compile_skill(name: str, request: Request) -> dict[str, str]:
    """Trigger compilation of a single skill by name."""
    import threading  # noqa: PLC0415
    import time  # noqa: PLC0415
    from pathlib import Path  # noqa: PLC0415, TC003

    from harness_poc.core.config import HarnessConfig  # noqa: PLC0415
    from harness_poc.core.skills.skill_compiler import (  # noqa: PLC0415
        _build_skill_compiled_event,
        _rejected_bundle,
        compile_skill,
        get_compilation_status,
        publish_compile_event,
    )
    from harness_poc.core.skills.skill_runner import SkillRunner  # noqa: PLC0415
    from harness_poc.core.storage import (  # noqa: PLC0415
        BlackboardDatabase,
        create_db_engine,
    )

    model = request.app.state.compiler_model
    if model is None:
        return {
            "status": "error",
            "detail": "LLM model not available — check API keys and provider configuration",
        }

    # Prevent concurrent batch + single-skill compilation
    status = get_compilation_status()
    if status.get("running"):
        return {"status": "error", "detail": "A batch compilation is already in progress"}

    config = HarnessConfig.load()
    knowledge_dirs = [config.paths.project_skills]
    if config.paths.system_skills.exists():
        knowledge_dirs.append(config.paths.system_skills)

    skill_file: Path | None = None
    for d in knowledge_dirs:
        if not d.exists():
            continue
        for sf in sorted(d.glob("*/SKILL.md")):
            if sf.parent.name == name:
                skill_file = sf
                break
        if skill_file is not None:
            break

    if skill_file is None:
        return {"status": "not_found"}

    def _compile_one() -> None:
        db = BlackboardDatabase(create_db_engine(config.runtime.database_url))
        # Emit initial progress so the frontend shows progress bar immediately
        publish_compile_event({
            "event": "compilation_progress",
            "total": 1,
            "completed": 0,
            "errors": 0,
            "running": True,
        })
        runner = SkillRunner(database=db, config=config)
        try:
            bundle = compile_skill(
                skill_file,  # type: ignore[arg-type]
                skill_runner=runner,
                force=True,
                model=model,
                compiler_config=config.compiler,
            )
        except Exception as exc:
            bundle = _rejected_bundle(skill_file, [str(exc)])
            bundle.compiled_at = time.time()
        publish_compile_event(_build_skill_compiled_event(name, bundle))
        # Signal completion so the frontend knows to close the stream
        publish_compile_event(
            {
                "event": "compilation_done",
                "total": 1,
                "completed": 1,
                "errors": 1 if bundle.compilation_status == "rejected" else 0,
            }
        )

    threading.Thread(target=_compile_one, daemon=True).start()
    return {"status": "started"}


@router.get("/api/skills/compile/stream")
async def stream_compilation(request: Request) -> StreamingResponse:
    """Server-Sent Events stream of compilation progress.

    Emits a snapshot of current progress on connect (if compilation is running),
    then pushes per-skill events as they complete.  Multiple browser tabs each
    get their own queue via the fan-out in skill_compiler.py.
    """
    from harness_poc.core.skills.skill_compiler import (  # noqa: PLC0415
        get_compilation_status,
        subscribe_compile_events,
        unsubscribe_compile_events,
    )

    queue = subscribe_compile_events()

    async def event_generator():
        try:
            # Snapshot on connect: if compilation is already running, emit
            # current progress so late-joining clients see the correct state.
            status = get_compilation_status()
            if status.get("running"):
                snapshot = {
                    "event": "compilation_progress",
                    "total": int(status.get("total", 0)),
                    "completed": int(status.get("completed", 0)),
                    "errors": int(status.get("errors", 0)),
                    "running": True,
                }
                yield f"event: compilation_progress\ndata: {json.dumps(snapshot)}\n\n"

            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=10.0)
                    yield (f"event: {event['event']}\ndata: {json.dumps(event, default=str)}\n\n")
                except TimeoutError:
                    # Keepalive — prevents proxy/CDN from closing idle connection.
                    # 10s is safe for nginx (60s default), ALB (60s), Cloudflare (100s).
                    yield ": keepalive\n\n"
        finally:
            unsubscribe_compile_events(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
