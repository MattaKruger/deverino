"""read_project_state — read durable project state at runtime.

Returns the current project state so the agent can reference past
decisions, constraints, open questions, facts, and other institutional
knowledge during task execution.  Always reads fresh from the database.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from harness_poc.core.skills import SkillResult

if TYPE_CHECKING:
    from harness_poc.core.tools import ToolContext

_READABLE_SECTIONS = frozenset(
    {
        "summary",
        "notes",
        "decisions",
        "next_actions",
        "open_questions",
        "constraints",
        "changelog",
        "facts",
        "all",
    }
)


def _render_section(state: Any, section: str) -> str:  # noqa: ANN401
    """Render a single section of the project state as markdown.

    *state* is a StatePayload at runtime; typed as Any to avoid a
    circular import (ToolContext → BlackboardProxy → StatePayload).
    """
    if section == "all":
        return state.to_markdown("Project State")  # type: ignore[attr-defined]
    if section == "summary":
        return state.summary or "_No summary yet._"  # type: ignore[attr-defined]
    if section == "facts":
        facts: dict[str, str] = state.facts  # type: ignore[attr-defined]
        if not facts:
            return "_No facts set._"
        return "### Facts\n\n" + "\n".join(f"- **{k}**: {v}" for k, v in sorted(facts.items()))
    values: list[str] = getattr(state, section, [])
    if not values:
        return f"_No {section} entries._"
    heading = section.replace("_", " ").title()
    lines = [f"### {heading}", ""]
    for i, entry in enumerate(values, 1):
        lines.append(f"{i}. {entry}")
    return "\n".join(lines)


def read_project_state(
    ctx: ToolContext,
    section: str = "all",
) -> SkillResult:
    """Read durable project state.

    Args:
        ctx: Tool execution context.
        section: Which section to return.
    """
    section = (section or "all").strip().lower()

    if section not in _READABLE_SECTIONS:
        valid = ", ".join(sorted(_READABLE_SECTIONS))
        return SkillResult(
            status="failed",
            content=f"Invalid section {section!r}. Choose from: {valid}.",
        )

    if ctx.database is None:
        return SkillResult(
            status="failed",
            content="Database not available for read_project_state.",
        )

    try:
        state = ctx.database.ensure_project_state()
    except Exception as exc:
        return SkillResult(
            status="failed",
            content=f"Failed to read project state: {exc}",
        )

    content = _render_section(state, section)
    return SkillResult(
        status="success",
        content=content,
        artifacts={"section": section},
    )


# ── Register ──────────────────────────────────────────────────────────

from harness_poc.system_tools import register as _register  # noqa: E402

_register(
    name="read_project_state",
    description=(
        "Read durable project state. Returns notes, decisions, constraints, "
        "facts, open questions, and other institutional knowledge from past "
        "sessions. Use this to check what the team has already decided or "
        "discovered before taking action."
    ),
    parameters={
        "type": "object",
        "properties": {
            "section": {
                "type": "string",
                "description": (
                    "Which section to read: summary, notes, decisions, "
                    "next_actions, open_questions, constraints, changelog, "
                    "facts, or all (default)."
                ),
            },
        },
    },
    handler=read_project_state,
)
