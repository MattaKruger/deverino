"""LLM Distiller stage — strict schema, bounded retry, safe fallback."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Sequence
from importlib import resources
from typing import cast

from pydantic import ValidationError
from pydantic_ai import Agent
from pydantic_ai.models import Model

from harness_poc.core.context_map.config import DistillerConfig
from harness_poc.core.context_map.schema import DistilledBatch, DistillerEntry, MapEntry
from harness_poc.core.events.context_map_events import ContextMapEvent

logger = logging.getLogger(__name__)


def _load_prompt(template_name: str) -> str:
    package = "harness_poc.core.context_map.prompts"
    filename = f"{template_name}.md"
    return resources.files(package).joinpath(filename).read_text(encoding="utf-8")


def _render_events(events: Sequence[ContextMapEvent]) -> str:
    payload = [e.model_dump() for e in events]
    return json.dumps({"events": payload}, indent=2, default=str)


def _render_current_map(entries: Sequence[MapEntry]) -> str:
    """Render map entries as stable context for the distiller — down-sampled.

    Sends only the essential orientation: full key list, the 10 most recently
    updated entries, and high-priority entries (>=0.7).  The distiller needs
    to know what exists, not see a full replica of the map.
    """
    if not entries:
        return json.dumps({"prior_keys": [], "recent_entries": [], "high_priority_entries": []})

    prior_keys = [e.key for e in entries]

    # Sort by last_updated descending for recency (explicit — DB order not guaranteed)
    sorted_by_recency = sorted(entries, key=lambda e: e.last_updated, reverse=True)
    recent_entries = sorted_by_recency[:10]
    recent_keys = {e.key for e in recent_entries}

    # High-priority entries not already in recent_entries
    high_priority_entries = [e for e in entries if e.priority >= 0.7 and e.key not in recent_keys]

    return json.dumps(
        {
            "prior_keys": prior_keys,
            "recent_entries": [
                {
                    "key": e.key,
                    "observation_type": e.observation_type,
                    "summary": e.summary,
                    "priority": e.priority,
                }
                for e in recent_entries
            ],
            "high_priority_entries": [
                {
                    "key": e.key,
                    "observation_type": e.observation_type,
                    "summary": e.summary,
                    "priority": e.priority,
                }
                for e in high_priority_entries
            ],
        },
        indent=2,
    )


def _validate_against_events(
    batch: DistilledBatch,
    known_event_ids: set[str],
) -> list[str]:
    errors: list[str] = []
    for entry in batch.entries:
        unknown = [eid for eid in entry.source_event_ids if eid not in known_event_ids]
        if unknown:
            errors.append(f"entry {entry.key!r} cites unknown source_event_ids: {unknown}")
    return errors


async def run_distiller(
    events: Sequence[ContextMapEvent],
    model: Model,
    config: DistillerConfig,
    *,
    current_map: Sequence[MapEntry] | None = None,
) -> list[DistillerEntry]:
    """Run one Distiller cycle. Returns [] on any unrecoverable failure (safe fallback)."""
    t0 = time.monotonic()
    template = config.prompt_template_compact or config.prompt_template
    system_prompt = _load_prompt(template)
    agent = Agent(
        model=model,
        output_type=DistilledBatch,
        system_prompt=system_prompt,
        model_settings={"timeout": config.timeout_seconds},
    )
    known_ids = {e.event_id for e in events}

    # Build user prompt: current map context → events payload
    current_map_context = _render_current_map(current_map) if current_map else ""
    events_payload = _render_events(events)
    if current_map_context:
        user_prompt = f"{current_map_context}\n\n{events_payload}"
    else:
        user_prompt = events_payload

    logger.debug(
        "Distiller starting: %d events, %d map entries, %.0fs timeout, %d max retries",
        len(events),
        len(current_map) if current_map else 0,
        config.timeout_seconds,
        config.max_retries,
    )

    last_error: str | None = None
    for attempt in range(config.max_retries + 1):
        prompt = user_prompt
        if last_error is not None:
            prompt = (
                f"{user_prompt}\n\n"
                f"Previous output was rejected: {last_error}. "
                "Reissue conforming output."
            )
        try:
            t_attempt = time.monotonic()
            run = await asyncio.wait_for(agent.run(prompt), timeout=config.timeout_seconds)
            elapsed = time.monotonic() - t_attempt
            logger.debug("Distiller attempt %d completed in %.1fs", attempt + 1, elapsed)
            batch: DistilledBatch = cast("DistilledBatch", run.output)
        except TimeoutError:
            last_error = f"LLM call timed out after {config.timeout_seconds}s"
            logger.warning(
                "Distiller attempt %d timed out after %.0fs", attempt + 1, config.timeout_seconds
            )
            continue
        except ValidationError as exc:
            last_error = f"schema validation failed: {exc}"
            logger.warning("Distiller attempt %d validation failed: %s", attempt + 1, exc)
            continue

        errors = _validate_against_events(batch, known_ids)
        if not errors:
            total_elapsed = time.monotonic() - t0
            logger.debug(
                "Distiller succeeded in %.1fs (%d attempt(s), %d entries distilled)",
                total_elapsed,
                attempt + 1,
                len(batch.entries),
            )
            return list(batch.entries)
        last_error = "; ".join(errors)

    total_elapsed = time.monotonic() - t0
    logger.warning(
        "Distiller failed after %d attempt(s) in %.1fs — returning empty",
        config.max_retries + 1,
        total_elapsed,
    )
    return []  # safe fallback after max_retries
