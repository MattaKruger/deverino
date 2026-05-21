from __future__ import annotations

import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from pydantic_ai.messages import ModelMessagesTypeAdapter
from sqlalchemy.exc import OperationalError as SAOperationalError

from harness_poc.core.blackboard_proxy import BlackboardAccessProxy
from harness_poc.core.config import HarnessConfig
from harness_poc.core.database import BlackboardDatabase
from harness_poc.core.db_engine import create_db_engine
from harness_poc.core.document_index import DocumentIndexer
from harness_poc.core.event_bus import EventBus
from harness_poc.core.event_store import EventStore
from harness_poc.core.logging import configure_logging
from harness_poc.core.permissions import SkillPermissions
from harness_poc.core.pipeline_runner import PipelineRunner
from harness_poc.core.pydantic_runtime import (
    PydanticAgentRuntime,
    build_runtime,
)
from harness_poc.core.skill_catalog import build_skill_catalog
from harness_poc.core.skill_runner import SkillRunner
from harness_poc.core.skill_scaffolder import SkillScaffolder
from harness_poc.core.state import build_state_context
from harness_poc.core.tool_runner import ToolRunner
from harness_poc.core.vespa_client import LiveVespaDocumentClient
from harness_poc.core.workflow_runner import WorkflowRunner
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

    from harness_poc.core.llm_client import Message
    from harness_poc.core.materializer_runner import MaterializerRunner


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


@dataclass(slots=True)
class AppState:
    session_id: str
    database: BlackboardDatabase
    config: HarnessConfig
    skill_runner: SkillRunner
    tool_runner: ToolRunner
    skill_scaffolder: SkillScaffolder
    workflow_runner: WorkflowRunner
    pipeline_runner: PipelineRunner
    pydantic_runtime: PydanticAgentRuntime
    pydantic_messages: list[ModelMessage]
    goal_decision_model: Model | None
    messages: list[Message]
    tools: list[dict[str, Any]]
    event_bus: EventBus
    streaming: StreamingContext
    materializer_runner: MaterializerRunner | None = None


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
    paths = _resolve_auto_index_paths(config)
    if paths is None:
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
    except Exception:  # noqa: BLE001
        logger.info("Skipping auto-index: Vespa not reachable")
        return

    _run_auto_index(config, database, paths)


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


def _run_auto_index(
    config: HarnessConfig, database: BlackboardDatabase, paths: list[str]
) -> None:
    """Feed chunks to Vespa and write metadata to the database."""
    vespa = LiveVespaDocumentClient(config.retrieval)
    indexer = DocumentIndexer(
        config=config.retrieval,
        database=database,
        vespa_client=vespa,
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
        print(f"done ({", ".join(parts)})")
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


def build_app_state(session_id: str | None = None) -> AppState:
    config = HarnessConfig.load()
    configure_logging(config.project_root)

    engine = create_db_engine(config.runtime.database_url)
    database = BlackboardDatabase(engine)
    database.create_tables()
    event_store = EventStore(engine)

    system_prompt = config.paths.soul.read_text(encoding="utf-8")
    resumed = session_id is not None
    if resumed:
        if not database.session_exists(session_id):  # type: ignore[arg-type]
            msg = f"Session {session_id} not found"
            raise ValueError(msg)
    else:
        session_id = database.start_session("Interactive proof of concept session.")
    assert session_id is not None  # noqa: S101
    project_state = database.ensure_project_state()
    session_state = database.ensure_session_state(session_id)
    corpus_key = f"{config.project_id}:default"
    context_map = database.get_context_map(corpus_key)
    context_map_block = ""
    if context_map:
        context_map_block = f"--- Context Map ---\n{json.dumps(context_map, indent=2)}\n---"
    state_context = build_state_context(project_state, session_state)
    skill_runner = SkillRunner(database=database, config=config)
    db_proxy = BlackboardAccessProxy(database, _permissive_for_tools())
    tool_runner = ToolRunner(
        config=config,
        skill_runner=skill_runner,
        database=db_proxy,
        runtime_config=config.runtime,
    )
    workflow_runner = WorkflowRunner(skill_runner)
    pipeline_runner = PipelineRunner(config.paths.pipelines)
    messages: list[Message] = [
        {
            "role": "system",
            "content": "\n\n".join(
                filter(
                    None,
                    [
                        system_prompt,
                        state_context,
                        context_map_block or None,
                    ],
                ),
            ),
        },
    ]
    tools = skill_runner.discover_skills()
    full_system_prompt = "\n\n".join(
        filter(
            None,
            [
                system_prompt,
                state_context,
                context_map_block or None,
            ],
        ),
    )
    event_bus = EventBus(event_store)
    from harness_poc.core.materializer_runner import MaterializerRunner  # noqa: PLC0415

    materializer = MaterializerRunner(
        db=database,
        skill_runner=skill_runner,
        config=config,
        session_id=session_id,
        poll_interval=config.runtime.materializer_poll_interval,
    )

    if config.observability.logfire_enabled:
        from harness_poc.core.logfire_subscriber import (  # noqa: PLC0415
            configure_logfire,
            wire_logfire,
        )

        configure_logfire(include_content=config.observability.logfire_include_content)
        wire_logfire(event_bus)

    # ── Knowledge skill context ────────────────────────────────────
    knowledge_dirs = [config.paths.project_skills]
    if config.paths.system_skills.exists():
        knowledge_dirs.append(config.paths.system_skills)
    init_knowledge_context(
        knowledge_dirs,
        project_root=config.project_root,
        scratch_base=None,
        session_id=session_id,
    )
    skill_catalog = build_skill_catalog(knowledge_dirs)

    restored_messages: list[ModelMessage] = []
    if resumed:
        blob = database.load_session_messages(session_id)
        if blob:
            restored_messages = ModelMessagesTypeAdapter.validate_python(blob)
            restored_messages = _ensure_history_consistent(restored_messages)

    return AppState(
        session_id=session_id,
        database=database,
        config=config,
        skill_runner=skill_runner,
        tool_runner=tool_runner,
        skill_scaffolder=SkillScaffolder(config),
        workflow_runner=workflow_runner,
        pipeline_runner=pipeline_runner,
        pydantic_runtime=build_runtime(
            session_id=session_id,
            database=database,
            config=config,
            skill_runner=skill_runner,
            tool_runner=tool_runner,
            system_prompt=full_system_prompt,
            llm=config.llm,
            enable_tools=True,
            blocked_skills=_TUI_BLOCKED_SKILLS,
            skill_catalog=skill_catalog,
        ),
        pydantic_messages=restored_messages,
        goal_decision_model=None,
        messages=messages,
        tools=tools,
        event_bus=event_bus,
        streaming=StreamingContext(),
        materializer_runner=materializer,
    )
