"""Shared context-map formatting functions used by both old and v2 paths.

Extracted from ``harness_poc.v2.context_engine.ContextEngine`` so that
``app_factory.py`` (old chat path) and ``wiring.py`` (v2 pipeline/react path)
use the same persona lens, verified state, working context, and context window
formatting.  Single source of truth for prompt-block assembly.
"""

from __future__ import annotations

from typing import Any


def format_persona_lens(persona_text: str, pedagogy_text: str) -> str:
    """Combine persona and pedagogy into a unified filtering lens block."""
    return (
        "--- Unified Persona + Pedagogy Lens ---\n\n"
        f"{persona_text}\n\n"
        "--- Developer Pedagogy Profile ---\n\n"
        f"{pedagogy_text}\n\n"
        "--- End Unified Lens ---"
    )


def format_verified_state(state: dict[str, Any]) -> str:
    """Render verified state as a compact key-value block."""
    lines: list[str] = []
    for k, v in state.items():
        if isinstance(v, dict):
            lines.append(f"{k}:")
            for sk, sv in v.items():
                lines.append(f"  {sk}: {sv}")
        elif isinstance(v, list):
            lines.append(f"{k}: [{', '.join(str(x) for x in v)}]")
        else:
            lines.append(f"{k}: {v}")
    return "\n".join(lines)


def format_working_context(ctx: dict[str, Any]) -> str:
    """Render working context as a compact summary block."""
    relevant = {"corpus", "goal", "session_id", "active_skill", "constraints"}
    lines: list[str] = [f"  {k}: {ctx[k]}" for k in sorted(relevant & set(ctx))]
    return "\n".join(lines)


def format_context_window(  # noqa: PLR0913
    rendered_map: str,
    *,
    persona_text: str | None = None,
    pedagogy_text: str | None = None,
    verified_state: dict[str, Any] | None = None,
    working_context: dict[str, Any] | None = None,
    post_map_block: str | None = None,
    map_label: str = "Context Map",
) -> str:
    """Format the complete context window for system prompt injection.

    Builds a multi-section block with optional layers.  Both the old chat
    path (``_system_message_for`` / ``build_runtime_layer``) and the v2
    path (``ContextEngine._format_context_window``) call through here
    with different optional sections populated.

    Args:
        rendered_map: The pre-rendered context map body string.
        persona_text: Optional persona markdown content.
        pedagogy_text: Optional pedagogy profile content.
        verified_state: Optional verified state dict from prior passes.
        working_context: Optional working context dict.
        post_map_block: Optional block appended immediately after the map
            (used by the old path for cross-corpus entries and inventory).
        map_label: Section header label (``"Context Map"`` for old path,
            ``"Materialized Context Map"`` for v2 path).

    Returns:
        A formatted multi-section string ready for system prompt assembly.
    """
    parts: list[str] = []

    if persona_text and pedagogy_text:
        parts.append(format_persona_lens(persona_text, pedagogy_text))

    if verified_state:
        parts.append("--- Verified Implementation State ---\n")
        parts.append(format_verified_state(verified_state))

    parts.append(f"--- {map_label} ---")
    parts.append(rendered_map)
    if post_map_block:
        parts.append(post_map_block)

    if working_context:
        parts.append("--- Active Working Context ---\n")
        parts.append(format_working_context(working_context))

    return "\n".join(parts)
