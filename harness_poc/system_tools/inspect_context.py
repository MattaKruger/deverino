"""inspect_own_context — inspect the agent's own system prompt.

Returns the full assembled system prompt text as injected at session start:
SOUL charter + STATE + context map + skill catalog + tool policy.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from harness_poc.core.skills import SkillResult

if TYPE_CHECKING:
    from harness_poc.core.tools import ToolContext


def inspect_own_context(
    ctx: ToolContext,
) -> SkillResult:
    """Return the agent's own system prompt.

    The system prompt is assembled at session start from multiple layers:
    SOUL charter, durable STATE, PEEK context map (if available),
    knowledge skill catalog, and tool usage policy. This tool returns
    the full text exactly as the model receives it.

    Use this to verify what context the agent is operating with, debug
    prompt assembly, or cross-reference against the ACDL specification.
    """
    prompt = ctx.system_prompt
    if not prompt:
        return SkillResult(
            status="failed",
            content="System prompt not available. The tool runner may not have "
            "been wired with the session's system prompt.",
        )

    # Lightweight structural summary alongside the raw text
    lines = prompt.split("\n")
    sections = [
        line.strip()
        for line in lines
        if line.startswith("## ") and not line.startswith("## Tool Result Policy")
    ]

    summary = {
        "total_chars": len(prompt),
        "total_words": len(prompt.split()),
        "total_lines": len(lines),
        "sections_found": sections,
    }

    return SkillResult(
        status="success",
        content=prompt,
        artifacts={
            "system_prompt_summary": summary,
            "system_prompt_full": prompt,
        },
    )


# ── Register ──────────────────────────────────────────────────────────

from harness_poc.system_tools import register as _register  # noqa: E402

_register(
    name="inspect_own_context",
    description=(
        "Return the agent's own full system prompt text. "
        "Use this to inspect what context the agent is operating with, "
        "cross-reference against the ACDL specification, or debug "
        "prompt assembly. Returns the raw text plus a structural summary "
        "(character/word/line counts, detected markdown sections)."
    ),
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
    handler=inspect_own_context,
)
