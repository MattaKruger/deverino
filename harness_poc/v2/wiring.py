"""V2 Wiring — bridges ContextEngine and ExecutionEngine into the harness runtime.

Provides factory functions that construct V2 engines from existing harness
infrastructure (database, config, skill runner). Designed to be called from
app_factory.py and CLI commands without modifying existing harness internals.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)
from typing import TYPE_CHECKING

from harness_poc.v2.runtime import V2Runtime

if TYPE_CHECKING:
    from harness_poc.app_factory import Identity
    from harness_poc.core.config import HarnessConfig
    from harness_poc.core.events.event_bus import EventBus
    from harness_poc.core.storage.database import BlackboardDatabase
    from harness_poc.v2.context_engine import ContextEngine
    from harness_poc.v2.contracts.sub_agent_spawner import DelegatedTaskOutput
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
    event_bus: EventBus | None = None,
) -> ContextEngine:
    """Build a ContextEngine from existing harness infrastructure.

    Uses the persona directory and pedagogy path from harness config.
    The materializer is a lightweight adapter over the existing
    ContextMapMaterializer contract.

    If event_bus is provided, all v2 events are routed through it
    instead of direct database writes.
    """
    from harness_poc.v2.context_engine import ContextEngine

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
    event_bus: EventBus | None = None,
) -> ExecutionEngine:
    """Build an ExecutionEngine from existing harness infrastructure.

    Wires the v2 delegate_task handler with real spawner, event bus,
    and blackboard writer. event_bus is required.
    """
    from harness_poc.v2.execution_engine import ExecutionEngine

    if event_bus is None:
        msg = "ExecutionEngine requires an event_bus"
        raise ValueError(msg)

    spawner = _build_spawner_adapter(config, db)
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
    from harness_poc.v2.workflow_orchestrator import (
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
    identity: Identity,
    config: HarnessConfig,
    *,
    mode: str = "pipeline",
    project_id: str = "deverino",
) -> V2Runtime:
    """Build a v2 runtime with mode-specific subscriber wiring.

    Uses the v1 EventBus from ``identity.event_bus`` for all pub/sub.
    Returns a typed ``V2Runtime`` whose fields are populated based on mode.

    Args:
        identity: Application identity with .event_bus and .database.
        config: The harness configuration.
        mode: ``"pipeline"`` or ``"react"``.
        project_id: Project identifier.

    Returns:
        ``V2Runtime`` — access ``.bus``, ``.mode``, and mode-specific fields.

    Raises:
        ValueError: If mode is unknown.
    """
    bus = identity.event_bus

    if mode == "pipeline":
        ctx_engine = build_context_engine(
            identity.database, config, project_id=project_id, event_bus=bus
        )
        exec_engine = build_execution_engine(
            identity.database, config, project_id=project_id, event_bus=bus
        )
        orch = build_workflow_orchestrator(ctx_engine, exec_engine, project_id=project_id)
        return V2Runtime(
            mode="pipeline",
            bus=bus,
            context_engine=ctx_engine,
            execution_engine=exec_engine,
            orchestrator=orch,
        )

    if mode == "react":
        from harness_poc.core.skills import SkillRunner
        from harness_poc.v2.subscribers.circuit_breaker import (
            CircuitBreaker,
        )
        from harness_poc.v2.subscribers.goal_evaluator import (
            GoalEvaluator,
        )
        from harness_poc.v2.subscribers.llm_worker import LlmWorker
        from harness_poc.v2.subscribers.tool_worker import ToolWorker

        db = identity.database
        skill_runner = SkillRunner(database=db, config=config)
        from harness_poc.v2.agent_config import set_skill_runner

        set_skill_runner(skill_runner)
        # Build context map block for system prompt injection
        context_map_block = build_v2_system_prompt_block(
            db, config, persona_id="coder", project_id=project_id
        )
        soul_text = config.paths.soul.read_text(encoding="utf-8")
        system_prompt = f"{soul_text}\n\n{context_map_block}" if context_map_block else soul_text

        llm_worker = LlmWorker(
            database=db,
            config=config,
            skill_runner=skill_runner,
            system_prompt=system_prompt,
        )
        tool_worker = ToolWorker(skill_runner=skill_runner)
        circuit_breaker = CircuitBreaker(
            max_retries=config.runtime.max_retries,
            max_tokens=config.runtime.max_tokens,
        )
        goal_evaluator = GoalEvaluator(
            max_iterations=50,
        )

        return V2Runtime(
            mode="react",
            bus=bus,
            llm_worker=llm_worker,
            tool_worker=tool_worker,
            circuit_breaker=circuit_breaker,
            goal_evaluator=goal_evaluator,
        )

    _msg = f"Unknown v2 mode '{mode}'. Expected 'pipeline' or 'react'."
    raise ValueError(_msg)


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
    from harness_poc.v2.context_engine import (
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


def _build_materializer_adapter(  # noqa: ANN202
    db: BlackboardDatabase,
    config: HarnessConfig,
):
    """Build a ContextMapMaterializer adapter from the harness database.

    Wraps the existing context map pipeline (Distiller → Cartographer)
    behind the V2 ContextMapMaterializer protocol.
    """
    from harness_poc.core.context_map.render import render_context_map
    from harness_poc.v2.contracts.context_map_pipeline import (
        DbContextMap,
    )

    class _HarnessMaterializer:
        def materialize(self, corpus_path: str) -> DbContextMap:
            corpus_name = corpus_path.rstrip("/").rsplit("/", 1)[-1] or "codebase"
            corpus_key = f"{config.project_id}:{corpus_name}"
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


def _build_spawner_adapter(config: HarnessConfig, db: BlackboardDatabase):  # noqa: ANN202
    """Build a SubAgentSpawner adapter that runs real sub-agents via the LLM.

    Reads persona templates from ``config.paths.personas``, builds a
    pydantic_ai Agent with the persona as system prompt, and runs the
    sub-agent synchronously. Returns DelegatedTaskResult with binary
    success/failed status.
    """
    import json as _json
    import uuid
    from typing import Any

    from pydantic_ai import Agent
    from pydantic_ai.exceptions import UsageLimitExceeded
    from pydantic_ai.models.test import TestModel
    from pydantic_ai.settings import ModelSettings
    from pydantic_ai.usage import UsageLimits

    from harness_poc.core.runtime import build_model
    from harness_poc.v2.contracts.sub_agent_spawner import (
        DELEGATED_STATUS_FAILED,
        DELEGATED_STATUS_SUCCESS,
        DelegatedTaskResult,
    )

    def _safe_output_text(value: Any) -> str:  # noqa: ANN401
        """Convert agent output to a bounded, JSON-safe string."""
        if isinstance(value, str):
            return value[:100_000]
        try:
            serialized = _json.dumps(value, default=str)
            return serialized[:100_000]
        except TypeError, ValueError:
            return repr(value)[:1000]

    max_error_length = 500

    def _format_exception(exc: BaseException) -> str:
        """Format an exception for the error field, bounded to 500 chars."""
        msg = str(exc)
        if len(msg) > max_error_length:
            msg = msg[:max_error_length] + "..."
        return f"{type(exc).__name__}: {msg}"

    def _fallback_model() -> TestModel:
        return TestModel()

    class _HarnessSpawner:
        def spawn(self, task_spec: dict) -> DelegatedTaskResult:  # noqa: PLR0912
            task_id = task_spec.get("task_id", str(uuid.uuid4()))
            persona = str(task_spec.get("persona", ""))
            objective = str(task_spec.get("objective", ""))
            context = str(task_spec.get("context") or "")

            if not persona or not objective:
                return DelegatedTaskResult(
                    task_id=task_id,
                    status=DELEGATED_STATUS_FAILED,
                    error=f"task_spec requires 'persona' and 'objective'. Got persona={persona!r}, objective={objective!r}",
                )

            # Load persona template
            try:
                persona_path = config.paths.personas / f"{persona}.md"
                if persona_path.exists():
                    system_prompt = persona_path.read_text(encoding="utf-8")
                else:
                    system_prompt = (
                        f"You are a {persona} agent. Complete the assigned task "
                        f"concisely and accurately."
                    )
            except OSError as exc:
                return DelegatedTaskResult(
                    task_id=task_id,
                    status=DELEGATED_STATUS_FAILED,
                    error=f"Failed to load persona '{persona}': {exc}",
                )

            # Load context map for sub-agent orientation
            corpus_key = str(task_spec.get("corpus_key") or "")
            if not corpus_key:
                corpus_key = f"{config.project_id}:subagent:{persona}"
            context_map_block = ""
            try:
                current_map = db.get_context_map(corpus_key) or []
                if current_map:
                    from harness_poc.core.context_map.render import render_context_map

                    cycle_n = db.get_cycle(corpus_key)
                    context_map_block = render_context_map(
                        current_map, cycle_n, prompt_mode="structured"
                    )
            except Exception:
                logger.debug(
                    "Failed to load context map for sub-agent (corpus_key=%s)",
                    corpus_key,
                    exc_info=True,
                )
            if context_map_block:
                system_prompt += f"\n\n--- Context Map ({corpus_key}) ---\n{context_map_block}\n---"

            # Also inject the project-level context map so sub-agents have
            # general project context in addition to their persona-specific map.
            project_corpus_key = f"{config.project_id}:codebase"
            if project_corpus_key != corpus_key:
                try:
                    project_map = db.get_context_map(project_corpus_key) or []
                    if project_map:
                        project_cycle = db.get_cycle(project_corpus_key)
                        project_block = render_context_map(
                            project_map, project_cycle, prompt_mode="structured"
                        )
                        system_prompt += (
                            f"\n\n--- Project Context Map ({project_corpus_key}) ---\n"
                            f"{project_block}\n---"
                        )
                except Exception:
                    logger.debug(
                        "Failed to load project context map for sub-agent (corpus_key=%s)",
                        project_corpus_key,
                        exc_info=True,
                    )
            # Load agent configuration (tools, permissions)
            tools: list = []
            try:
                from harness_poc.system_tools import get_registry
                from harness_poc.v2.agent_config import AgentConfig

                agents_dir = config.project_root / "subagents"
                agent_cfg = AgentConfig.from_name(agents_dir, persona, tool_registry=get_registry())
                tools = agent_cfg.tools
            except FileNotFoundError:
                logger.debug("No agent config for persona '%s' — running with no tools", persona)
            except Exception:
                logger.warning(
                    "Failed to load agent config for persona '%s' — running with no tools",
                    persona,
                    exc_info=True,
                )

            # Build and run the sub-agent
            try:
                model = build_model(config.llm, fallback_model=_fallback_model())
                agent = Agent(
                    model,
                    system_prompt=system_prompt,
                    tools=tools or None,
                )
                prompt = f"Objective: {objective}"
                if context:
                    prompt += f"\n\nContext: {context}"
                result = agent.run_sync(
                    prompt,
                    model_settings=ModelSettings(max_tokens=8192),
                    usage_limits=UsageLimits(
                        request_limit=30,
                        tool_calls_limit=20,
                        total_tokens_limit=200_000,
                        output_tokens_limit=8192,
                    ),
                )
                output_text = _safe_output_text(result.output)

                return DelegatedTaskResult(
                    task_id=task_id,
                    status=DELEGATED_STATUS_SUCCESS,
                    raw_output={
                        "persona": persona,
                        "objective": objective,
                        "output": output_text,
                    },
                )
            except UsageLimitExceeded as exc:
                hint = (
                    "Token budget exceeded. Break this task into smaller pieces, "
                    "or narrow the objective to require fewer tool calls. "
                    f"({_format_exception(exc)})"
                )
                return DelegatedTaskResult(
                    task_id=task_id,
                    status=DELEGATED_STATUS_FAILED,
                    error=hint,
                )
            except Exception as exc:
                return DelegatedTaskResult(
                    task_id=task_id,
                    status=DELEGATED_STATUS_FAILED,
                    error=f"Sub-agent execution failed: {_format_exception(exc)}",
                )

    return _HarnessSpawner()


def _build_blackboard_adapter(db: BlackboardDatabase):  # noqa: ANN202
    """Build a BlackboardWriter adapter over the harness database."""

    class _HarnessBlackboard:
        def write(self, task_id: str, output: DelegatedTaskOutput, session_id: str) -> None:
            # Write the delegated output to shared memory
            db.write_memory(
                session_id=session_id,
                key=f"delegate_task:{task_id}",
                payload={
                    "task_id": output.task_id,
                    "output_label": output.output_label,
                    "summary": output.summary,
                    "raw_output": output.raw_output,
                    "metadata": getattr(output, "metadata", {}),
                },
            )

    return _HarnessBlackboard()


# ---------------------------------------------------------------------------
# Soul adapter
# ---------------------------------------------------------------------------


def build_soul_constitution(config: HarnessConfig):  # noqa: ANN201
    """Build a SoulConstitution adapter from the SOUL.md file.

    Parses ``## N. Section Name`` headings and exposes section access
    via the SoulConstitution protocol. Validation checks the contract's
    REQUIRED_SECTIONS against the actual sections present in the file.

    Returns an object satisfying the SoulConstitution protocol.

    Raises:
        FileNotFoundError: If SOUL.md does not exist at config.paths.soul.
        SoulIntegrityError: If the SOUL file has no parseable sections.
    """
    from harness_poc.v2.contracts.soul_constitution import (
        REQUIRED_SECTIONS,
        SoulIntegrityError,
    )

    soul_path = config.paths.soul
    if not soul_path.exists():
        _msg = f"SOUL.md not found at {soul_path}"
        raise FileNotFoundError(_msg)

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
