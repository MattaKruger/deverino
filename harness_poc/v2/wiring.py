"""V2 Wiring — bridges ContextEngine and ExecutionEngine into the harness runtime.

Provides factory functions that construct V2 engines from existing harness
infrastructure (database, config, skill runner). Designed to be called from
app_factory.py and CLI commands without modifying existing harness internals.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

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
) -> ContextEngine:
    """Build a ContextEngine from existing harness infrastructure.

    Uses the persona directory and pedagogy path from harness config.
    The materializer is a lightweight adapter over the existing
    ContextMapMaterializer contract.
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
    """Build an EventBus adapter that writes events to the database."""

    class _HarnessEventBus:
        def subscribe(self, event_type: str, handler) -> None:
            pass  # no-op for now

        def unsubscribe(self, event_type: str, handler) -> None:
            pass

        def publish(self, event_type: str, payload: dict) -> None:
            pass  # events are written directly via db.append_context_event

    return _HarnessEventBus()


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
