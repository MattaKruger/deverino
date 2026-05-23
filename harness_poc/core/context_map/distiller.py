"""LLM Distiller stage — strict schema, bounded retry, safe fallback."""

from __future__ import annotations

import json
from collections.abc import Sequence
from importlib import resources
from typing import cast

from pydantic import ValidationError
from pydantic_ai import Agent
from pydantic_ai.models import Model

from harness_poc.core.context_map.config import DistillerConfig
from harness_poc.core.context_map.schema import DistilledBatch, DistillerEntry
from harness_poc.core.events.context_map_events import ContextMapEvent


def _load_prompt(template_name: str) -> str:
    package = "harness_poc.core.context_map.prompts"
    filename = f"{template_name}.md"
    return resources.files(package).joinpath(filename).read_text(encoding="utf-8")


def _render_events(events: Sequence[ContextMapEvent]) -> str:
    payload = [e.model_dump() for e in events]
    return json.dumps({"events": payload}, indent=2, default=str)


def _validate_against_events(
    batch: DistilledBatch,
    known_event_ids: set[str],
) -> list[str]:
    errors: list[str] = []
    for entry in batch.entries:
        unknown = [eid for eid in entry.source_event_ids if eid not in known_event_ids]
        if unknown:
            errors.append(
                f"entry {entry.key!r} cites unknown source_event_ids: {unknown}"
            )
    return errors


async def run_distiller(
    events: Sequence[ContextMapEvent],
    model: Model,
    config: DistillerConfig,
) -> list[DistillerEntry]:
    """Run one Distiller cycle. Returns [] on any unrecoverable failure (safe fallback)."""
    system_prompt = _load_prompt(config.prompt_template)
    agent = Agent(model=model, output_type=DistilledBatch, system_prompt=system_prompt)
    known_ids = {e.event_id for e in events}
    user_prompt = _render_events(events)

    last_error: str | None = None
    for _attempt in range(config.max_retries + 1):
        prompt = user_prompt
        if last_error is not None:
            prompt = (
                f"{user_prompt}\n\n"
                f"Previous output was rejected: {last_error}. "
                "Reissue conforming output."
            )
        try:
            run = await agent.run(prompt)
            batch: DistilledBatch = cast("DistilledBatch", run.output)
        except ValidationError as exc:
            last_error = f"schema validation failed: {exc}"
            continue

        errors = _validate_against_events(batch, known_ids)
        if not errors:
            return list(batch.entries)
        last_error = "; ".join(errors)

    return []  # safe fallback after max_retries
