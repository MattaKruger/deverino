"""V2 Wiring — bridges ContextEngine and ExecutionEngine into the harness runtime.

Provides factory functions that construct V2 engines from existing harness
infrastructure (database, config, skill runner). Designed to be called from
app_factory.py and CLI commands without modifying existing harness internals.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from harness_poc.core.config import HarnessConfig
    from harness_poc.core.storage.database import BlackboardDatabase
    from harness_poc.v2.context_engine import ContextEngine
    from harness_poc.v2.execution_engine import ExecutionEngine
    from harness_poc.v2.workflow_orchestrator import WorkflowOrchestrator


# ---------------------------------------------------------------------------
# Engine factories
# ---------------------------------------------------------------------------


def build_context_engine(
    db: BlackboardDatabase,
    config: HarnessConfig,
    *,
    project_id: str = "deverino",
    event_bus: Any = None,
) -> ContextEngine:
    """Build a ContextEngine from existing harness infrastructure.

    Uses the persona directory and pedagogy path from harness config.
    The materializer is a lightweight adapter over the existing
    ContextMapMaterializer contract.

    If event_bus is provided, all v2 events are routed through it
    instead of direct database writes.
    """
    from harness_poc.v2.context_engine import ContextEngine  # noqa: PLC0415

    materializer = _build_materializer_adapter(db, config)

    return ContextEngine(
        db=db,
        materializer=materializer,
        personas_dir=config.paths.personas,
        pedagogy_path=config.project_root
        / ".agents"
        / "skills"
        / "developer-pedagogy"
        / "SKILL.md",
        project_id=project_id,
        event_bus=event_bus,
    )


def build_execution_engine(
    db: BlackboardDatabase,
    config: HarnessConfig,
    *,
    project_id: str = "deverino",
    max_background_agents: int = 5,
) -> ExecutionEngine:
    """Build an ExecutionEngine from existing harness infrastructure.

    Wires the v2 delegate_task handler with real spawner, event bus,
    and blackboard writer.
    """
    from harness_poc.v2.execution_engine import ExecutionEngine  # noqa: PLC0415

    spawner = _build_spawner_adapter(config)
    event_bus = _build_event_bus_adapter(db)
    blackboard = _build_blackboard_adapter(db)

    return ExecutionEngine(
        db=db,
        spawner=spawner,
        event_bus=event_bus,
        blackboard=blackboard,
        project_id=project_id,
        max_background_agents=max_background_agents,
    )


def build_workflow_orchestrator(
    context_engine: ContextEngine,
    execution_engine: ExecutionEngine,
    *,
    sandbox_timeout_seconds: int = 30,
    project_id: str = "deverino",
) -> WorkflowOrchestrator:
    """Build a WorkflowOrchestrator from pre-built engines."""
    from harness_poc.v2.workflow_orchestrator import (  # noqa: PLC0415
        WorkflowOrchestrator,
    )

    return WorkflowOrchestrator(
        context_engine=context_engine,
        execution_engine=execution_engine,
        sandbox_timeout_seconds=sandbox_timeout_seconds,
        project_id=project_id,
    )


# ---------------------------------------------------------------------------
# System prompt augmentation
# ---------------------------------------------------------------------------


def build_v2_runtime(
    db: BlackboardDatabase,
    config: HarnessConfig,
    *,
    mode: str = "pipeline",
    project_id: str = "deverino",
):
    """Build a v2 runtime with mode-specific subscriber wiring.

    Creates the shared event bus adapter and returns it along with
    mode-specific engines/subscribers. Callers start the appropriate
    execution path based on mode:

    - ``"pipeline"``: returns (bus, ctx_engine, exec_engine, orchestrator).
      The orchestrator's ``run_pipeline_via_bus`` handles subscription
      internally.

    - ``"react"``: returns (bus, llm_worker, tool_worker, circuit_breaker,
      goal_evaluator). The caller runs these as async tasks.

    Args:
        db: The harness database.
        config: The harness configuration.
        mode: ``"pipeline"`` or ``"react"``.
        project_id: Project identifier.

    Returns:
        A dict with keys depending on mode. Always includes ``"bus"``.

    Raises:
        ValueError: If mode is unknown.
    """
    bus = _build_event_bus_adapter(db)

    if mode == "pipeline":
        ctx_engine = build_context_engine(
            db, config, project_id=project_id, event_bus=bus
        )
        exec_engine = build_execution_engine(
            db, config, project_id=project_id
        )
        orch = build_workflow_orchestrator(
            ctx_engine, exec_engine, project_id=project_id
        )
        return {
            "mode": "pipeline",
            "bus": bus,
            "context_engine": ctx_engine,
            "execution_engine": exec_engine,
            "orchestrator": orch,
        }

    if mode == "react":
        from harness_poc.v2.subscribers.circuit_breaker import (  # noqa: PLC0415
            CircuitBreaker,
        )
        from harness_poc.v2.subscribers.goal_evaluator import (  # noqa: PLC0415
            GoalEvaluator,
        )
        from harness_poc.v2.subscribers.llm_worker import LlmWorker  # noqa: PLC0415
        from harness_poc.v2.subscribers.tool_worker import ToolWorker  # noqa: PLC0415

        from harness_poc.core.skills import SkillRunner  # noqa: PLC0415

        skill_runner = SkillRunner(database=db, config=config)

        llm_worker = LlmWorker(
            database=db,
            config=config,
            skill_runner=skill_runner,
        )
        tool_worker = ToolWorker(skill_runner=skill_runner)
        circuit_breaker = CircuitBreaker(
            max_retries=config.runtime.max_retries,
            max_tokens=config.runtime.max_tokens,
        )
        goal_evaluator = GoalEvaluator(
            max_iterations=50,
        )

        return {
            "mode": "react",
            "bus": bus,
            "llm_worker": llm_worker,
            "tool_worker": tool_worker,
            "circuit_breaker": circuit_breaker,
            "goal_evaluator": goal_evaluator,
        }

    raise ValueError(
        f"Unknown v2 mode '{mode}'. Expected 'pipeline' or 'react'."
    )


# ---------------------------------------------------------------------------
# System prompt augmentation
# ---------------------------------------------------------------------------


def build_v2_system_prompt_block(
    db: BlackboardDatabase,
    config: HarnessConfig,
    *,
    persona_id: str = "coder",
    working_context: dict | None = None,
    project_id: str = "deverino",
) -> str:
    """Build a V2-augmented system prompt block using the ContextEngine.

    Returns the rendered prompt from materialize_context_map(), which
    includes the unified persona+pedagogy lens and the filtered context map.
    Intended to replace or augment the raw context map block in
    _system_message_for().

    Args:
        db: The harness database.
        config: The harness configuration.
        persona_id: The persona to use (e.g. "coder", "architect", "reviewer").
        working_context: Optional dict with session context.
        project_id: Project identifier.

    Returns:
        A rendered prompt string ready for system message injection.
    """
    from harness_poc.v2.context_engine import (  # noqa: PLC0415
        PedagogyNotFoundError,
        PersonaNotFoundError,
    )

    ctx_engine = build_context_engine(db, config, project_id=project_id)

    try:
        result = ctx_engine.materialize_context_map(
            working_context=working_context or {},
            persona_id=persona_id,
            corpus_path="docs/",
        )
        return result["rendered_prompt"]
    except (PersonaNotFoundError, PedagogyNotFoundError) as exc:
        # Fall back gracefully — return empty block
        import logging

        logger = logging.getLogger(__name__)
        logger.warning("V2 context materialization skipped: %s", exc)
        return ""


# ---------------------------------------------------------------------------
# Internal adapters
# ---------------------------------------------------------------------------


def _build_materializer_adapter(
    db: BlackboardDatabase,
    config: HarnessConfig,
):
    """Build a ContextMapMaterializer adapter from the harness database.

    Wraps the existing context map pipeline (Distiller → Cartographer)
    behind the V2 ContextMapMaterializer protocol.
    """
    from harness_poc.core.context_map.render import render_context_map  # noqa: PLC0415
    from harness_poc.v2.contracts.context_map_pipeline import (  # noqa: PLC0415
        DbContextMap,
    )

    class _HarnessMaterializer:
        def materialize(self, corpus_path: str) -> DbContextMap:
            corpus_key = f"{config.project_id}:codebase"
            current_map = db.get_context_map(corpus_key) or []
            cycle_n = db.get_cycle(corpus_key)
            if not current_map:
                return DbContextMap(
                    map_id="empty",
                    rendered="",
                    render_mode="full",
                    source_paths=[corpus_path],
                    token_count=0,
                    stages_run=["noop"],
                )
            rendered = render_context_map(current_map, cycle_n, prompt_mode="structured")
            token_count = sum(getattr(e, "token_estimate", 0) for e in current_map)
            return DbContextMap(
                map_id=f"{corpus_key}@{cycle_n}",
                rendered=rendered,
                render_mode="structured",
                source_paths=[corpus_path],
                token_count=token_count,
                stages_run=["ingest", "index", "retrieve", "assemble", "render"],
            )

    return _HarnessMaterializer()


def _build_spawner_adapter(config: HarnessConfig):
    """Build a SubAgentSpawner adapter from the harness skill runner.

    Uses the context-map-materializer skill pattern to execute sub-agents.
    For now, returns a stub that delegates through the existing
    delegate_task handler interface.
    """
    from harness_poc.v2.contracts.sub_agent_spawner import (  # noqa: PLC0415
        DELEGATED_STATUS_SUCCESS,
        DelegatedTaskResult,
    )

    class _HarnessSpawner:
        def spawn(self, task_spec: dict) -> DelegatedTaskResult:
            # Stub: returns success for non-streaming spawn.
            # Real implementation would invoke the LLM loop for the sub-agent.
            import uuid

            task_id = task_spec.get("task_id", str(uuid.uuid4()))
            return DelegatedTaskResult(
                task_id=task_id,
                status=DELEGATED_STATUS_SUCCESS,
                raw_output={
                    "persona": task_spec.get("persona"),
                    "objective": task_spec.get("objective"),
                    "note": "Sub-agent spawned via harness adapter (stub)",
                },
            )

    return _HarnessSpawner()


def _build_event_bus_adapter(db: BlackboardDatabase):
    """Build an EventBus adapter with persistence and real pub/sub dispatch.

    Persists every published event via ``db.append_context_event()`` and
    dispatches to registered synchronous handlers. Also exposes an async
    session-scoped subscription path (``subscribe_session``) for ReAct mode.

    The session_id for persistence is extracted from the payload (key
    ``session_id``) or falls back to ``"v2-runtime"``.
    """
    import asyncio
    import logging
    from collections import defaultdict

    from harness_poc.v2.contracts.event_runtime import EventHandler

    logger = logging.getLogger(__name__)

    class _V2EventBus:
        """Real EventBus adapter satisfying the v2 EventBus protocol.

        Synchronous pub/sub with persistence + optional async session
        subscriptions for ReAct mode workers.
        """

        def __init__(self) -> None:
            # Per-event-type synchronous handlers: event_type → list[EventHandler]
            self._handlers: dict[str, list[EventHandler]] = defaultdict(list)
            # Async session queues for ReAct mode: session_id → list[asyncio.Queue]
            self._async_queues: dict[str, list[asyncio.Queue[dict]]] = defaultdict(list)

        # ----- v2 EventBus protocol ------------------------------------

        def subscribe(self, event_type: str, handler: EventHandler) -> None:
            """Register a synchronous handler for an event type."""
            self._handlers[event_type].append(handler)

        def unsubscribe(self, event_type: str, handler: EventHandler) -> None:
            """Remove a previously registered handler."""
            try:
                self._handlers[event_type].remove(handler)
            except ValueError:
                pass

        def publish(self, event_type: str, payload: dict) -> None:
            """Persist and dispatch an event.

            Persists via ``db.append_context_event()``, then calls all
            registered synchronous handlers and delivers to async session
            queues.
            """
            session_id = payload.get("session_id", "v2-runtime")
            team_member = payload.get("team_member", "v2")

            # Persist
            try:
                db.append_context_event(
                    session_id=session_id,
                    team_member=team_member,
                    event_type=event_type,
                    payload=payload,
                )
            except Exception:
                logger.exception(
                    "Failed to persist event type=%s session=%s",
                    event_type,
                    session_id,
                )

            # Dispatch to synchronous handlers
            for handler in list(self._handlers.get(event_type, [])):
                try:
                    handler(event_type, payload)
                except Exception:
                    logger.exception(
                        "Event handler raised for event_type=%s", event_type
                    )

            # Dispatch to async session queues
            event_envelope = {"event_type": event_type, "payload": payload}
            for queue in list(self._async_queues.get(session_id, [])):
                try:
                    queue.put_nowait(event_envelope)
                except asyncio.QueueFull:
                    logger.warning(
                        "Async queue full for session=%s event_type=%s",
                        session_id,
                        event_type,
                    )

        # ----- Async session-scoped subscription (ReAct mode) ----------

        async def subscribe_session(
            self, session_id: str
        ) -> "AsyncGenerator[dict, None]":
            """Async generator yielding events for a session.

            Used by ReAct mode workers to receive all events for their
            session as they are published.
            """
            import asyncio

            queue: asyncio.Queue[dict] = asyncio.Queue()
            self._async_queues[session_id].append(queue)
            try:
                while True:
                    event = await queue.get()
                    yield event
            finally:
                try:
                    self._async_queues[session_id].remove(queue)
                except ValueError:
                    pass

    return _V2EventBus()


def _build_blackboard_adapter(db: BlackboardDatabase):
    """Build a BlackboardWriter adapter over the harness database."""

    class _HarnessBlackboard:
        def write(self, task_id: str, output) -> None:
            # Write the delegated output to shared memory
            import json

            db.write_memory(
                session_id="v2-orchestrator",
                key=f"delegated:{task_id}",
                data=json.dumps(
                    {
                        "task_id": output.task_id,
                        "output_label": output.output_label,
                        "summary": output.summary,
                    }
                ),
            )

    return _HarnessBlackboard()


# ---------------------------------------------------------------------------
# Soul adapter
# ---------------------------------------------------------------------------


def build_soul_constitution(config: HarnessConfig):
    """Build a SoulConstitution adapter from the SOUL.md file.

    Parses ``## N. Section Name`` headings and exposes section access
    via the SoulConstitution protocol. Validation checks the contract's
    REQUIRED_SECTIONS against the actual sections present in the file.

    Returns an object satisfying the SoulConstitution protocol.

    Raises:
        FileNotFoundError: If SOUL.md does not exist at config.paths.soul.
        SoulIntegrityError: If the SOUL file has no parseable sections.
    """
    from pathlib import Path
    from harness_poc.v2.contracts.soul_constitution import (
        REQUIRED_SECTIONS,
        SoulIntegrityError,
    )

    soul_path = config.paths.soul
    if not soul_path.exists():
        raise FileNotFoundError(f"SOUL.md not found at {soul_path}")

    raw = soul_path.read_text(encoding="utf-8")
    parsed = _parse_soul_sections(raw)

    if not parsed:
        raise SoulIntegrityError(
            missing=REQUIRED_SECTIONS,
            extra=set(),
        )

    class _HarnessSoul:
        @property
        def sections(self) -> set[str]:
            return set(parsed.keys())

        def get(self, section: str) -> str | None:
            return parsed.get(section)

        def validate(self) -> None:
            actual = set(parsed.keys())
            missing = REQUIRED_SECTIONS - actual
            extra = actual - REQUIRED_SECTIONS
            if missing:
                raise SoulIntegrityError(missing=missing, extra=extra)

    return _HarnessSoul()


def _parse_soul_sections(raw: str) -> dict[str, str]:
    """Parse ``## N. Section Name`` headings and their body text.

    Extracts the section name (everything after the leading number
    and dot, e.g. "Operating Principles" from "## 2. Operating Principles")
    and collects all lines until the next ``##`` heading as the body.
    """
    import re

    sections: dict[str, str] = {}
    current_name: str | None = None
    current_lines: list[str] = []

    heading_re = re.compile(r"^##\s+(?:\d+\.\s+)?(.+)$")

    for line in raw.splitlines():
        m = heading_re.match(line)
        if m:
            if current_name is not None:
                sections[current_name] = "\n".join(current_lines).strip()
            current_name = m.group(1).strip()
            current_lines = []
        elif current_name is not None:
            current_lines.append(line)

    if current_name is not None:
        sections[current_name] = "\n".join(current_lines).strip()

    return sections
