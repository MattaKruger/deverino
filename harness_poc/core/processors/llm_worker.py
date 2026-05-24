from __future__ import annotations

import asyncio
import json
import logging
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

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from collections.abc import Iterable

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

    Runs immediately before LLMTextEmitted is published. Cross-corpus citations
    are attributed to the source corpus, not the active one.
    """
    active_corpus_key = database.get_session_corpus_key(
        session_id,
        default=f"{config.project_id}:codebase",
    )

    cc = config.cartographer
    if not cc.cross_corpus_enabled:
        related_keys: list[str] = []
    elif cc.cross_corpus_auto_discover:
        all_keys = database.get_all_corpus_keys()
        related_keys = [k for k in all_keys if k != active_corpus_key]
        # Optional whitelist filter — when configured for this active key,
        # restrict the auto-discovered set to it.
        whitelist = cc.cross_corpus_related_corpora.get(active_corpus_key)
        if whitelist:
            whitelist_set = set(whitelist)
            related_keys = [k for k in related_keys if k in whitelist_set]
    else:
        related_keys = cc.cross_corpus_related_corpora.get(active_corpus_key, [])

    # (entry, source_corpus_key) keyed by both dashed and undashed entry_id.
    # Active corpus wins on collision (see _index_active below).
    lookup: dict[str, tuple[object, str]] = {}

    def _index_related(entries: Iterable[object], source: str) -> None:
        for entry in entries:
            entry_id = getattr(entry, "entry_id", "")
            if not entry_id:
                continue
            lookup.setdefault(entry_id.replace("-", ""), (entry, source))
            lookup.setdefault(entry_id, (entry, source))

    def _index_active(entries: Iterable[object]) -> None:
        # Explicit overwrite — active corpus is authoritative on duplicate ids.
        for entry in entries:
            entry_id = getattr(entry, "entry_id", "")
            if not entry_id:
                continue
            lookup[entry_id.replace("-", "")] = (entry, active_corpus_key)
            lookup[entry_id] = (entry, active_corpus_key)

    related_maps = database.get_context_maps(related_keys) if related_keys else {}
    for source_key, entries in related_maps.items():
        _index_related(entries, source_key)
    _index_active(database.get_context_map(active_corpus_key) or [])

    # Per-turn dedup keyed on (source_corpus, entry_id). Same id in two corpora
    # is theoretical but the dedup must not collapse them.
    seen: set[tuple[str, str]] = set()
    refs: list[MapEntryReferenced] = []
    cycle_cache: dict[str, int] = {}

    for match in _CITATION_RE.finditer(content):
        entry_id = match.group(1)
        hit = lookup.get(entry_id)
        if hit is None:
            logger.warning(
                "Unresolved [entry:%s] citation. active=%s related=%s known=%s",
                entry_id,
                active_corpus_key,
                related_keys,
                database.get_all_corpus_keys(),
            )
            continue
        entry, source_corpus = hit
        dedup_key = (source_corpus, entry_id)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        if source_corpus not in cycle_cache:
            cycle_cache[source_corpus] = database.get_cycle(source_corpus)

        refs.append(
            MapEntryReferenced(
                session_id=session_id,
                corpus_key=source_corpus,
                entry_id=entry_id,
                entry_key=str(getattr(entry, "key", "")),
                section=str(getattr(entry, "section", "")),
                cycle_n=cycle_cache[source_corpus],
                citation_context=content[
                    max(0, match.start() - 80) : match.end() + 80
                ],
            )
        )

    return refs
