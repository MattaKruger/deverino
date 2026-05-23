from __future__ import annotations

import asyncio
import json
import re
from typing import TYPE_CHECKING, Any

from harness_poc.core.events import (
    AgentInputAdded,
    LLMActionEmitted,
    LLMTextEmitted,
    MapEntryReferenced,
    SkillCompleted,
    SkillRequested,
    StreamPaused,
)
from harness_poc.core.runtime import account_for_model_run, build_runtime, derive_session_state

if TYPE_CHECKING:
    from harness_poc.core.config import HarnessConfig
    from harness_poc.core.events import EventBus
    from harness_poc.core.runtime import PydanticAgentRuntime
    from harness_poc.core.skills import SkillRunner
    from harness_poc.core.storage import BlackboardDatabase


async def run_llm_worker(  # noqa: PLR0913
    bus: EventBus,
    session_id: str,
    database: BlackboardDatabase,
    config: HarnessConfig,
    skill_runner: SkillRunner,
    system_prompt: str | None = None,
    runtime: PydanticAgentRuntime | None = None,
) -> None:
    llm_runtime = runtime or build_runtime(
        session_id=session_id,
        database=database,
        config=config,
        skill_runner=skill_runner,
        system_prompt=system_prompt or config.paths.soul.read_text(encoding="utf-8"),
        llm=config.llm,
        enable_tools=False,
    )

    async for event in bus.subscribe_session(session_id):
        if isinstance(event, StreamPaused):
            break
        if not isinstance(event, (AgentInputAdded, SkillCompleted)):
            continue

        state = await derive_session_state(database, session_id)
        if state.get("stream_paused"):
            break

        prompt = _prompt_from_event(event)
        result = await asyncio.to_thread(llm_runtime.run_text, prompt)
        if result.usage is not None:
            accounting = account_for_model_run(result.usage, new_messages=result.messages)
            await bus.publish_async(
                LLMActionEmitted(
                    session_id=session_id,
                    model=config.llm.model,
                    tokens_used=accounting.new_tokens,
                    input_tokens=accounting.input_tokens,
                    output_tokens=accounting.output_tokens,
                    billable_tokens=accounting.billable_tokens,
                    new_tokens=accounting.new_tokens,
                ),
            )

        requested_skill = _parse_skill_request(result.content)
        if requested_skill is not None:
            await bus.publish_async(SkillRequested(session_id=session_id, **requested_skill))
        elif result.content:
            # Extract and emit MapEntryReferenced events (Track B §4.2)
            for ref in _extract_references(
                result.content, session_id, database, config
            ):
                database.append_context_map_event(ref)
            await bus.publish_async(
                LLMTextEmitted(session_id=session_id, content=result.content),
            )


def _prompt_from_event(event: AgentInputAdded | SkillCompleted) -> str:
    if isinstance(event, AgentInputAdded):
        return event.user_content
    return "\n".join(
        [
            f"Skill {event.tool_name or event.skill_name} completed with {event.status}.",
            event.content or event.result,
        ],
    )


def _parse_skill_request(content: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None

    skill_name = parsed.get("skill_name") or parsed.get("tool_name")
    arguments = parsed.get("arguments", {})
    if not isinstance(skill_name, str) or not isinstance(arguments, dict):
        return None
    return {"skill_name": skill_name, "arguments": arguments}


# Regex for [entry:<32-char-hex>] citation markers (uuid4 hex form, no dashes)
_CITATION_RE = re.compile(r"\[entry:([0-9a-f]{32})\]")


def _extract_references(
    content: str,
    session_id: str,
    database: BlackboardDatabase,
    config: HarnessConfig,
) -> list[MapEntryReferenced]:
    """Scan assistant output for [entry:<id>] markers and emit MapEntryReferenced events.

    Track B §4.2: Inline regex post-processor that runs immediately before
    LLMTextEmitted is published.
    """
    import logging

    logger = logging.getLogger(__name__)

    # Resolve corpus_key — derive from project config (no session state dependency)
    corpus_key = f"{config.project_id}:codebase"

    cycle_n = database.get_cycle(corpus_key)
    context_map = database.get_context_map(corpus_key) or []

    # Check related corpora too (cross-corpus case, §4.3)
    cc = config.cartographer
    related_keys: list[str] = []
    if cc.cross_corpus_enabled:
        related_keys = cc.cross_corpus_related_corpora.get(corpus_key, [])
    related_maps = database.get_context_maps(related_keys) if related_keys else {}

    entries_by_id: dict[str, object] = {}
    for entry in context_map:
        entries_by_id[entry.entry_id.replace("-", "")] = entry
        entries_by_id[entry.entry_id] = entry
    for entries in related_maps.values():
        for entry in entries:
            entries_by_id[entry.entry_id.replace("-", "")] = entry
            entries_by_id[entry.entry_id] = entry

    seen: set[str] = set()
    refs: list[MapEntryReferenced] = []

    for match in _CITATION_RE.finditer(content):
        entry_id = match.group(1)
        if entry_id in seen:
            continue
        seen.add(entry_id)
        entry = entries_by_id.get(entry_id)
        if entry is None:
            # Marker points at evicted or unknown entry — log, do not emit
            logger.debug(
                "Citation marker references unknown entry_id=%s",
                entry_id,
            )
            continue
        # Get attributes from entry (could be MapEntry)
        entry_key = getattr(entry, "key", "")
        section = getattr(entry, "section", "")

        refs.append(
            MapEntryReferenced(
                session_id=session_id,
                corpus_key=corpus_key,
                entry_id=entry_id,
                entry_key=str(entry_key),
                section=str(section),
                cycle_n=cycle_n,
                citation_context=content[
                    max(0, match.start() - 80) : match.end() + 80
                ],
            )
        )

    return refs
