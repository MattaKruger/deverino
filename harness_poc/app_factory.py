from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from pydantic_ai.messages import ModelMessagesTypeAdapter
from sqlalchemy.exc import OperationalError as SAOperationalError

from harness_poc.core.config import HarnessConfig
from harness_poc.core.context_map.render import render_context_map
from harness_poc.core.events import EventBus, EventStore
from harness_poc.core.execution import PipelineRunner, WorkflowRunner
from harness_poc.core.logging import configure_logging
from harness_poc.core.permissions import SkillPermissions
from harness_poc.core.retrieval import (
    DocumentIndexer,
    LiveVespaDocumentClient,
    TextEmbedder,
    preload_embedder,
)
from harness_poc.core.runtime import (
    build_runtime,
)
from harness_poc.core.skills import SkillRunner, SkillScaffolder, build_skill_catalog
from harness_poc.core.storage import (
    BlackboardAccessProxy,
    BlackboardDatabase,
    create_db_engine,
)
from harness_poc.core.tools import ToolRunner
from harness_poc.core.tools.guards import (
    ContentGuard,
    GuardPipeline,
    IdempotencyGuard,
    PathGuard,
    QueryGuard,
    SizeGuard,
    TypeGuard,
)
from harness_poc.system_tools import get_registry
from harness_poc.system_tools.knowledge_tools import init_knowledge_context

logger = logging.getLogger(__name__)

# Skills excluded from the agent's auto-invokable toolset because they
# have workspace=read_write and could mutate project source files.
# The user can still invoke them explicitly via /skill <name>.
_TUI_BLOCKED_SKILLS: frozenset[str] = frozenset({"execute_python", "spec_writer"})

if TYPE_CHECKING:
    from collections.abc import Callable

    from pydantic_ai.messages import ModelMessage
    from pydantic_ai.models import Model

    from harness_poc.core.acdl.ast import ACDLFile
    from harness_poc.core.execution import MaterializerRunner
    from harness_poc.core.processors import ProcessorSupervisor
    from harness_poc.core.runtime import (
        Message,
        PydanticAgentRuntime,
    )
    from harness_poc.v2.wiring import V2Runtime


def _default_on_text(chunk: str) -> None:
    print(chunk, end="", flush=True)


def _default_on_finish(content: str) -> None:
    if content:
        print()


@dataclass
class StreamingContext:
    on_text: Callable[[str], None] = field(default_factory=lambda: _default_on_text)
    on_tool_event: Callable[[str], None] | None = None
    on_finish: Callable[[str], None] = field(default_factory=lambda: _default_on_finish)
    session_tokens: int = 0

    def reset_callbacks(self) -> None:
        self.on_text = _default_on_text
        self.on_tool_event = None
        self.on_finish = _default_on_finish


STARTUP_ERRORS = (
    OSError,
    RuntimeError,
    SAOperationalError,
    TypeError,
    ValueError,
    yaml.YAMLError,
)


@dataclass(frozen=True, slots=True)
class Identity:
    session_id: str
    database: BlackboardDatabase
    event_bus: EventBus
    event_store: EventStore
    config_project_root: Path
    config_project_id: str


@dataclass(slots=True)
class Runtime:
    config: HarnessConfig
    skill_runner: SkillRunner
    tool_runner: ToolRunner
    skill_scaffolder: SkillScaffolder
    workflow_runner: WorkflowRunner
    pipeline_runner: PipelineRunner
    pydantic_runtime: PydanticAgentRuntime
    tools: list[dict[str, Any]]
    skill_catalog: str


@dataclass(slots=True)
class LongLived:
    materializer_runner: MaterializerRunner
    supervisor: ProcessorSupervisor


@dataclass(slots=True)
class ActiveRunHandle:
    kind: str
    name: str
    started_at: str


@dataclass(slots=True)
class AppState:
    identity: Identity
    runtime: Runtime
    long_lived: LongLived
    pydantic_messages: list[ModelMessage]
    goal_decision_model: Model | None
    messages: list[Message]
    streaming: StreamingContext
    v2_runtime: V2Runtime | None = None
    # Default interaction is the v2 ReAct event loop. Native streaming chat is
    # still reachable via `/mode chat`.
    active_mode: str = "react"
    active_run: ActiveRunHandle | None = None

    def __getattr__(self, name: str) -> Any:  # noqa: ANN401
        for sub in (self.identity, self.runtime, self.long_lived):
            try:
                return getattr(sub, name)
            except AttributeError:
                continue
        msg = f"{type(self).__name__!r} has no attribute {name!r}"
        raise AttributeError(msg)

    @property
    def tools(self) -> list[dict[str, Any]]:
        return self.runtime.tools

    @tools.setter
    def tools(self, value: list[dict[str, Any]]) -> None:
        self.runtime.tools = value


def _check_vespa_health(config: HarnessConfig) -> None:
    """Check Vespa health — isolated so it can run with a timeout."""
    vespa = LiveVespaDocumentClient(config.retrieval)
    vespa.health_check()


def bootstrap_document_index(config: HarnessConfig, database: BlackboardDatabase) -> None:
    """Auto-index project documents on startup when retrieval is enabled.

    Called from interactive entry points (REPL, goal). No-op when
    retrieval is disabled, auto_index_paths is empty, the target paths
    don't exist on disk, Vespa is unreachable, or HARNESS_SKIP_AUTO_INDEX
    is set in the environment.
    """
    # Preload the embedding model in a background thread so the first
    # search_documents call doesn't incur a ~20 s cold-start HuggingFace
    # download.  The TUI starts immediately; searches queue until loaded.
    if config.retrieval.enabled:
        from threading import Thread  # noqa: PLC0415

        t = Thread(target=preload_embedder, daemon=True, name="embedder-preload")
        t.start()

    paths = _resolve_auto_index_paths(config)
    if paths is None:
        return

    changed_paths = _changed_auto_index_paths(config, database, paths)
    if not changed_paths:
        logger.info("Skipping auto-index: indexed documents are unchanged")
        return

    try:
        executor = ThreadPoolExecutor(max_workers=1)
        try:
            future = executor.submit(_check_vespa_health, config)
            future.result(timeout=3.0)
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
    except FutureTimeoutError:
        logger.info("Skipping auto-index: Vespa health check timed out")
        return
    except Exception:
        logger.info("Skipping auto-index: Vespa not reachable")
        return

    _run_auto_index(config, database, changed_paths)


def _changed_auto_index_paths(
    config: HarnessConfig, database: BlackboardDatabase, paths: list[str]
) -> list[str]:
    """Return only auto-index paths whose file hashes are stale or missing."""
    indexer = DocumentIndexer(
        config=config.retrieval,
        database=database,
        vespa_client=LiveVespaDocumentClient(config.retrieval),
    )
    return indexer.changed_indexable_uris(
        project_root=config.project_root,
        paths=paths,
    )


def _resolve_auto_index_paths(config: HarnessConfig) -> list[str] | None:
    """Return the list of paths to auto-index, or None if indexing should be skipped."""
    if os.environ.get("HARNESS_SKIP_AUTO_INDEX"):
        logger.info("Skipping auto-index: HARNESS_SKIP_AUTO_INDEX is set")
        return None
    if not config.retrieval.enabled:
        return None
    paths = config.retrieval.auto_index_paths
    if not paths:
        return None

    any_exists = False
    for p in paths:
        candidate = config.project_root / p if not Path(p).is_absolute() else Path(p)
        if candidate.exists():
            any_exists = True
            break
    return paths if any_exists else None


def _run_auto_index(config: HarnessConfig, database: BlackboardDatabase, paths: list[str]) -> None:
    """Feed chunks to Vespa and write metadata to the database."""
    vespa = LiveVespaDocumentClient(config.retrieval)
    embedder = TextEmbedder()
    indexer = DocumentIndexer(
        config=config.retrieval,
        database=database,
        vespa_client=vespa,
        embedder=embedder,
    )
    print("Indexing project documents...", end=" ", flush=True)
    try:
        result = indexer.index_paths(
            project_root=config.project_root,
            paths=paths,
        )
        parts = []
        if result.indexed:
            parts.append(f"{result.indexed} indexed")
        if result.skipped:
            parts.append(f"{result.skipped} skipped")
        if result.failed:
            parts.append(f"{result.failed} failed")
        print(f"done ({', '.join(parts)})")
    except Exception:
        logger.exception("Auto-index failed")
        print("failed")


def _permissive_for_tools() -> SkillPermissions:
    """Full permissions for built-in tools (read_write + blackboard access)."""
    return SkillPermissions(blackboard="read_write", workspace="read_write")


def _ensure_history_consistent(messages: list[ModelMessage]) -> list[ModelMessage]:
    """Repair history if the last turn ended mid-tool-call.

    A process killed between a ModelResponse with ToolCallPart and the matching
    ToolReturnPart leaves pydantic-ai's history invalid. Inject a synthetic
    return so the next agent.run succeeds.
    """
    from pydantic_ai.messages import (  # noqa: PLC0415
        ModelRequest,
        ModelResponse,
        ToolCallPart,
        ToolReturnPart,
    )

    if not messages:
        return messages
    last = messages[-1]
    if not isinstance(last, ModelResponse):
        return messages
    pending: list[ToolCallPart] = [p for p in last.parts if isinstance(p, ToolCallPart)]
    if not pending:
        return messages
    repair = ModelRequest(
        parts=[
            ToolReturnPart(
                tool_name=call.tool_name,
                content="interrupted by process exit",
                tool_call_id=call.tool_call_id,
            )
            for call in pending
        ]
    )
    return [*messages, repair]


def _resolve_or_create_session(
    database: BlackboardDatabase,
    session_id: str | None,
    *,
    corpus_key: str | None = None,
) -> str:
    if session_id is not None:
        if not database.session_exists(session_id):
            msg = f"Session {session_id} not found"
            raise ValueError(msg)
        return session_id
    return database.start_session(
        "Interactive proof of concept session.",
        active_corpus_key=corpus_key,
    )


def build_identity(
    config: HarnessConfig,
    session_id: str | None,
    *,
    database_url: str | None = None,
    corpus_key: str | None = None,
) -> Identity:
    effective_url = database_url or config.runtime.database_url
    engine = create_db_engine(effective_url)
    database = BlackboardDatabase(engine)
    database.create_tables()
    event_store = EventStore(engine)
    event_bus = EventBus(event_store)
    effective_session_id = _resolve_or_create_session(
        database,
        session_id,
        corpus_key=corpus_key,
    )
    return Identity(
        session_id=effective_session_id,
        database=database,
        event_bus=event_bus,
        event_store=event_store,
        config_project_root=config.project_root,
        config_project_id=config.project_id,
    )


def _resolve_soul_prompt(config: HarnessConfig) -> str:
    """Return the SOUL system prompt, preferring the compact variant when available."""
    soul_path = (
        config.paths.soul_compact
        if config.paths.soul_compact is not None and config.paths.soul_compact.exists()
        else config.paths.soul
    )
    return soul_path.read_text(encoding="utf-8")


def build_runtime_layer(identity: Identity, config: HarnessConfig) -> Runtime:
    """Build the reloadable runtime layer."""
    full_system_prompt = compose_system_prompt(identity, config)

    skill_runner = SkillRunner(database=identity.database, config=config)
    db_proxy = BlackboardAccessProxy(identity.database, _permissive_for_tools())
    from harness_poc.v2.agent_config import set_skill_runner

    set_skill_runner(skill_runner)
    tool_runner = ToolRunner(
        config=config,
        skill_runner=skill_runner,
        database=db_proxy,
        runtime_config=config.runtime,
        guards=GuardPipeline(
            [
                PathGuard(project_root=config.project_root),
                SizeGuard(),
                TypeGuard(
                    schema_provider=lambda: {name: info for name, info in get_registry().items()}
                ),
                IdempotencyGuard(),
                ContentGuard(),
                QueryGuard(),
            ]
        ),
    )
    workflow_runner = WorkflowRunner(skill_runner)
    pipeline_runner = PipelineRunner(config.paths.pipelines)

    knowledge_dirs = [config.paths.project_skills]
    if config.paths.system_skills.exists():
        knowledge_dirs.append(config.paths.system_skills)
    init_knowledge_context(
        knowledge_dirs,
        project_root=config.project_root,
        scratch_base=None,
        session_id=identity.session_id,
        skill_runner=skill_runner,
    )

    # ── Background skill compilation ──
    if config.compiler.enabled:
        _start_background_compilation(knowledge_dirs, skill_runner, config)

    skill_catalog = build_skill_catalog(knowledge_dirs)
    tools = skill_runner.discover_skills()

    runtime = Runtime(
        config=config,
        skill_runner=skill_runner,
        tool_runner=tool_runner,
        skill_scaffolder=SkillScaffolder(config),
        workflow_runner=workflow_runner,
        pipeline_runner=pipeline_runner,
        pydantic_runtime=build_runtime(
            session_id=identity.session_id,
            database=identity.database,
            config=config,
            skill_runner=skill_runner,
            tool_runner=tool_runner,
            system_prompt=full_system_prompt,
            llm=config.llm,
            enable_tools=True,
            blocked_skills=_TUI_BLOCKED_SKILLS,
            skill_catalog=skill_catalog,
            retrieval_mode=os.environ.get(
                "HARNESS_CORPUS_RETRIEVAL", config.cartographer.cross_corpus_retrieval
            ),
        ),
        tools=tools,
        skill_catalog=skill_catalog,
    )

    # Expose the final assembled system prompt to tools so they can
    # inspect it at runtime (e.g., inspect_own_context).
    # PydanticAI stores system prompts as a tuple of strings in
    # _system_prompts — join them to get the full text.
    tool_runner.system_prompt = "\n\n".join(runtime.pydantic_runtime.agent._system_prompts)  # noqa: SLF001

    return runtime


def build_long_lived(identity: Identity, runtime: Runtime) -> LongLived:
    from harness_poc.core.execution import MaterializerRunner  # noqa: PLC0415
    from harness_poc.core.processors import ProcessorSupervisor  # noqa: PLC0415

    materializer = MaterializerRunner(
        db=identity.database,
        skill_runner=runtime.skill_runner,
        config=runtime.config,
        session_id=identity.session_id,
        poll_interval=runtime.config.runtime.materializer_poll_interval,
    )
    return LongLived(
        materializer_runner=materializer,
        supervisor=ProcessorSupervisor(identity),
    )


@lru_cache(maxsize=4)
def _load_react_spec(spec_path: Path) -> ACDLFile:
    """Parse the ReAct .acdl spec once per path. The spec drives prompt composition."""
    from harness_poc.core.acdl import parse  # noqa: PLC0415

    return parse(spec_path.read_text(encoding="utf-8"), filename=str(spec_path))


def compose_system_prompt(identity: Identity, config: HarnessConfig) -> str:
    """Assemble the system prompt — composition driven by the .acdl spec.

    Python computes the values (soul, state, context-map render); the spec's
    ``S:`` block owns fragment order, headers, and the context-map conditional.
    Shared by the message-history path (``_system_message_for``) and the
    runtime path (``build_runtime_layer``) so there's one source of truth.
    """
    from harness_poc.core.acdl.executor import assemble_system_prompt  # noqa: PLC0415

    project_state = identity.database.ensure_project_state()
    session_state = identity.database.ensure_session_state(identity.session_id)
    corpus_key = identity.database.get_session_corpus_key(
        identity.session_id,
        default=f"{identity.config_project_id}:codebase",
    )
    context_map = identity.database.get_context_map(corpus_key)
    cycle_n = identity.database.get_cycle(corpus_key)

    bindings = {
        "sys.soul_charter": _resolve_soul_prompt(config),
        "sys.project_state": project_state.to_markdown("Project State"),
        "sys.session_state": session_state.to_markdown("Current Session State"),
    }
    if context_map and config.cartographer.prompt_block != "none":
        map_body = render_context_map(
            context_map,
            cycle_n,
            prompt_mode=config.cartographer.prompt_block,
        )
        inventory = _render_corpus_inventory(identity, corpus_key)
        post_map = ""
        if inventory:
            post_map = f"\n---{inventory}"
        bindings["sys.context_map"] = map_body + post_map

    return assemble_system_prompt(_load_react_spec(config.paths.react_spec), bindings)


def _system_message_for(identity: Identity, config: HarnessConfig) -> Message:
    return {"role": "system", "content": compose_system_prompt(identity, config)}




def _render_corpus_inventory(
    identity: Identity,
    active_corpus_key: str,
) -> str:
    """Render a one-line-per-corpus inventory, or '' when redundant.

    Suppressed for single-corpus deployments — there's nothing to choose
    between, and the active corpus is already implicit in the map block.
    """
    keys = identity.database.get_all_corpus_keys()
    if len(keys) <= 1:
        return ""
    lines = ["\n--- Available Corpora ---"]
    for ck in keys:
        marker = " (primary)" if ck == active_corpus_key else ""
        lines.append(f"{ck}{marker}")
    return "\n".join(lines)


def _build_app_state_with(  # noqa: PLR0913
    *,
    identity: Identity,
    runtime: Runtime,
    long_lived: LongLived,
    config: HarnessConfig,
    session_id_was_resumed: bool,
    v2_runtime: V2Runtime | None = None,
    active_mode: str = "chat",
) -> AppState:
    messages: list[Message] = [_system_message_for(identity, config)]

    restored_messages: list[ModelMessage] = []
    if session_id_was_resumed:
        blob = identity.database.load_session_messages(identity.session_id)
        if blob:
            restored_messages = ModelMessagesTypeAdapter.validate_python(blob)
            restored_messages = _ensure_history_consistent(restored_messages)

    return AppState(
        identity=identity,
        runtime=runtime,
        long_lived=long_lived,
        pydantic_messages=restored_messages,
        goal_decision_model=None,
        messages=messages,
        streaming=StreamingContext(),
        v2_runtime=v2_runtime,
        active_mode=active_mode,
    )


def build_app_state(
    session_id: str | None = None,
    *,
    database_url: str | None = None,
    corpus_key: str | None = None,
    mode: str = "chat",
) -> AppState:
    config = HarnessConfig.load()
    configure_logging(config.project_root)
    logger.info(
        "Building app state: project=%s mode=%s db=%s",
        config.project_id,
        mode,
        config.runtime.database_url.split("@")[-1] if "@" in config.runtime.database_url else "...",
    )
    identity = build_identity(
        config,
        session_id,
        database_url=database_url,
        corpus_key=corpus_key,
    )
    runtime = build_runtime_layer(identity, config)
    long_lived = build_long_lived(identity, runtime)

    if config.observability.logfire_enabled:
        from harness_poc.core.observability import (  # noqa: PLC0415
            configure_logfire,
            wire_logfire,
        )

        configure_logfire(include_content=config.observability.logfire_include_content)
        wire_logfire(identity.event_bus)

    return _build_app_state_with(
        identity=identity,
        runtime=runtime,
        long_lived=long_lived,
        config=config,
        session_id_was_resumed=session_id is not None,
        v2_runtime=_build_v2_runtime_if_needed(identity, config, mode),
        active_mode=mode,
    )


def _build_v2_runtime_if_needed(
    identity: Identity, config: HarnessConfig, mode: str
) -> V2Runtime | None:
    """Build a V2Runtime when mode is 'pipeline' or 'react', else None."""
    if mode in ("pipeline", "react"):
        from harness_poc.v2.wiring import build_v2_runtime  # noqa: PLC0415

        return build_v2_runtime(identity, config, mode=mode)
    return None


def _start_background_compilation(
    knowledge_dirs: list[Path],
    skill_runner: SkillRunner,
    config: HarnessConfig,
) -> None:
    """Kick off background skill compilation after TUI startup.

    Builds a model and compiles all SKILL.md files in a daemon thread.
    The TUI starts immediately; bundles populate the cache as they complete.
    First ``skill_view()`` calls may return raw markdown until compilation
    finishes.
    """
    import threading  # noqa: PLC0415

    from harness_poc.core.runtime.pydantic_runtime import (  # noqa: PLC0415
        build_model,
    )
    from harness_poc.core.skills.skill_compiler import (  # noqa: PLC0415
        compile_skill,
        set_compilation_progress,
    )

    def _compile_all() -> None:
        # Resolve model with compiler overrides
        if config.compiler.model or config.compiler.provider:
            from harness_poc.core.config import LLMConfig  # noqa: PLC0415

            llm_cfg = LLMConfig(
                provider=config.compiler.provider or config.llm.provider,
                model=config.compiler.model or config.llm.model,
                base_url=config.llm.base_url,
            )
        else:
            llm_cfg = config.llm

        try:
            model = build_model(llm_cfg)
        except Exception:
            logger.warning(
                "Background compilation skipped: could not build LLM model "
                "(check API keys and provider configuration)"
            )
            return

        # Collect all SKILL.md files
        skill_files: list[Path] = []
        for d in knowledge_dirs:
            if not d.exists():
                continue
            skill_files.extend(sorted(d.glob("*/SKILL.md")))

        if not skill_files:
            return

        total = len(skill_files)
        set_compilation_progress(total=total, running=True)
        logger.info("Background skill compilation started (%d skills)", total)

        completed = 0
        errors = 0
        for skill_file in skill_files:
            try:
                compile_skill(
                    skill_file,
                    skill_runner=skill_runner,
                    force=True,
                    model=model,
                    compiler_config=config.compiler,
                )
                completed += 1
            except Exception:
                logger.warning("Compilation failed for %s", skill_file, exc_info=True)
                errors += 1
            set_compilation_progress(total=total, completed=completed, errors=errors)

        set_compilation_progress(running=False)
        logger.info(
            "Background compilation finished: %d/%d compiled, %d errors",
            completed,
            total,
            errors,
        )

    threading.Thread(target=_compile_all, daemon=True).start()
