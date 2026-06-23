"""LlmWorker — v2 ReAct subscriber for LLM inference.

Listens for AgentInputAdded and SkillCompleted events via the v1 EventBus's
async session subscription. On each input, runs the LLM and publishes
LLMActionEmitted, SkillRequested, or LLMTextEmitted.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable

    from harness_poc.core.config import HarnessConfig
    from harness_poc.core.runtime import PydanticAgentRuntime
    from harness_poc.core.skills import SkillRunner
    from harness_poc.core.storage import BlackboardDatabase

from harness_poc.core.events.events import (
    AgentInputAdded,
    LLMActionEmitted,
    LLMTextEmitted,
    MapEntryReferenced,
    SkillCompleted,
    SkillRequested,
    StreamPaused,
)

logger = logging.getLogger(__name__)


class LlmWorker:
    """ReAct LLM worker — runs the model in response to input/tool-completion events.

    Uses the v1 EventBus's async session subscription to receive events
    and publishes LLM results back through the same bus.
    """

    def __init__(
        self,
        database: BlackboardDatabase,
        config: HarnessConfig,
        skill_runner: SkillRunner,
        *,
        system_prompt: str | None = None,
        runtime: PydanticAgentRuntime | None = None,
    ) -> None:
        self._database = database
        self._config = config
        self._skill_runner = skill_runner
        self._system_prompt = system_prompt
        self._runtime = runtime

    async def run(self, bus: Any, session_id: str) -> None:  # noqa: ANN401
        """Run the LLM worker loop for a session.

        Listens via async session subscription and reacts to
        AgentInputAdded and SkillCompleted events.
        """
        from harness_poc.core.runtime import (
            account_for_model_run,
            build_runtime,
            derive_session_state,
        )

        llm_runtime = self._runtime or build_runtime(
            session_id=session_id,
            database=self._database,
            config=self._config,
            skill_runner=self._skill_runner,
            system_prompt=self._system_prompt
            or self._config.paths.soul.read_text(encoding="utf-8"),
            llm=self._config.llm,
            enable_tools=False,
        )

        async for event in bus.subscribe_session(session_id):
            if isinstance(event, StreamPaused):
                break
            if not isinstance(event, (AgentInputAdded, SkillCompleted)):
                continue

            state = await derive_session_state(self._database, session_id)
            if state.get("stream_paused"):
                break

            prompt = self._prompt_from_event(event)
            result = await asyncio.to_thread(llm_runtime.run_text, prompt)

            if result.usage is not None:
                accounting = account_for_model_run(result.usage, new_messages=result.messages)
                bus.publish(
                    LLMActionEmitted(
                        session_id=session_id,
                        model=self._config.llm.model,
                        tokens_used=accounting.new_tokens,
                        input_tokens=accounting.input_tokens,
                        output_tokens=accounting.output_tokens,
                        billable_tokens=accounting.billable_tokens,
                        new_tokens=accounting.new_tokens,
                    )
                )

            requested_skill = self._parse_skill_request(result.content)
            if requested_skill is not None:
                bus.publish(
                    SkillRequested(
                        session_id=session_id,
                        skill_name=requested_skill["skill_name"],
                        arguments=requested_skill["arguments"],
                    )
                )
            elif result.content:
                for ref in _extract_references(
                    result.content, session_id, self._database, self._config
                ):
                    self._database.append_context_map_event(ref)
                bus.publish(
                    LLMTextEmitted(
                        session_id=session_id,
                        content=result.content,
                    )
                )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _prompt_from_event(event: AgentInputAdded | SkillCompleted) -> str:
        if isinstance(event, AgentInputAdded):
            return event.user_content
        # SkillCompleted
        tool_name = event.skill_name or event.tool_name or "unknown"
        status = event.status
        content = event.content or event.result
        return f"Skill {tool_name} completed with {status}.\n{content}"

    @staticmethod
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
    are attributed to the source corpus, not the active one. Ported from the v1
    chat llm_worker so the react path keeps context-map citation provenance.
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
        whitelist = cc.cross_corpus_related_corpora.get(active_corpus_key)
        if whitelist:
            whitelist_set = set(whitelist)
            related_keys = [k for k in related_keys if k in whitelist_set]
    else:
        related_keys = cc.cross_corpus_related_corpora.get(active_corpus_key, [])

    lookup: dict[str, tuple[object, str]] = {}

    def _index_related(entries: Iterable[object], source: str) -> None:
        for entry in entries:
            entry_id = getattr(entry, "entry_id", "")
            if not entry_id:
                continue
            lookup.setdefault(entry_id.replace("-", ""), (entry, source))
            lookup.setdefault(entry_id, (entry, source))

    def _index_active(entries: Iterable[object]) -> None:
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
                citation_context=content[max(0, match.start() - 80) : match.end() + 80],
            )
        )

    return refs
