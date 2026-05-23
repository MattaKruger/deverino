"""Context map rendering for prompt injection.

Produces structured plain-text blocks with [entry:<id>] citation markers
that the §4.2 citation extractor keys off.

See docs/superpowers/specs/2026-05-24-deterministic-cartographer-deferred-features.md §4.1.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from harness_poc.core.context_map.schema import MapEntry

# Part 1 §4 priority order for sections (highest first)
_SECTION_DISPLAY_ORDER = [
    "parsing_schema",
    "reusable_results",
    "domain_constants",
    "context_understanding",
    "context_roadmap",
]


def render_context_map(
    entries: Sequence[MapEntry],
    cycle_n: int,
    *,
    prompt_mode: str = "structured",
) -> str:
    """Render a list[MapEntry] as a structured plain-text context map block.

    Args:
        entries: Current map entries.
        cycle_n: The cycle number to display in the header.
        prompt_mode:
            - ``"structured"``: Grouped by section, priority-sorted, with citation markers.
            - ``"json"``: Raw JSON dump (no citation markers, no learning).
            - ``"none"``: Empty string (map is present but hidden from the prompt).

    Returns:
        The rendered string to inject into the system prompt body.

    """
    if prompt_mode == "none":
        return ""
    if prompt_mode == "json":
        return json.dumps(
            [entry.model_dump(mode="json") for entry in entries],
            indent=2,
        )
    # Default: "structured" mode
    return _render_structured(entries, cycle_n)


def _render_structured(entries: Sequence[MapEntry], cycle_n: int) -> str:
    """Group entries by section, sort within sections, and render with citation markers."""
    by_section: dict[str, list[MapEntry]] = {}
    for entry in entries:
        by_section.setdefault(entry.section, []).append(entry)

    lines: list[str] = [f"cycle: {cycle_n}"]

    for section in _SECTION_DISPLAY_ORDER:
        section_entries = by_section.get(section)
        if not section_entries:
            continue
        # Sort by priority desc, then entry_id asc (stable)
        sorted_entries = sorted(
            section_entries,
            key=lambda e: (-e.priority, e.entry_id),
        )
        lines.append(f"section: {section}")
        for entry in sorted_entries:
            summary_one_line = _collapse_newlines(entry.summary)
            lines.append(
                f"  - [entry:{_entry_id_no_dashes(entry.entry_id)}] "
                f"(p={entry.priority:.2f}) {summary_one_line}"
            )

    return "\n".join(lines)


def _collapse_newlines(text: str) -> str:
    """Collapse newlines into a single space so summaries fit on one line."""
    return re.sub(r"\s+", " ", text).strip()


def _entry_id_no_dashes(entry_id: str) -> str:
    """Strip dashes from UUIDs for citation markers (compact 32-char hex)."""
    return entry_id.replace("-", "")
