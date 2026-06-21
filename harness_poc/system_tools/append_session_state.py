"""append_session_state — record findings into session state autonomously.

Lets the agent take notes, log decisions, flag open questions, and
track next actions during task execution.  These accumulate in session
state and can later be proposed for promotion into durable project state
via the consolidate_state skill.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from harness_poc.core.skills import SkillResult

if TYPE_CHECKING:
    from harness_poc.core.tools import ToolContext

_APPENDABLE_SECTIONS: frozenset[str] = frozenset(
    {"notes", "decisions", "next_actions", "open_questions", "changelog"}
)

_SECTION_LABELS: dict[str, str] = {
    "notes": "Notes",
    "decisions": "Decisions",
    "next_actions": "Next Actions",
    "open_questions": "Open Questions",
    "changelog": "Changelog",
}


def append_session_state(
    ctx: ToolContext,
    section: str = "",
    text: str = "",
) -> SkillResult:
    """Append an entry to the session state.

    Args:
        ctx: Tool execution context.
        section: Which section to append to.
        text: The entry text to record.
    """
    section = (section or "").strip().lower()
    text = (text or "").strip()

    if section not in _APPENDABLE_SECTIONS:
        valid = ", ".join(sorted(_APPENDABLE_SECTIONS))
        return SkillResult(
            status="failed",
            content=f"Invalid section {section!r}. Choose from: {valid}.",
        )

    if not text:
        return SkillResult(
            status="failed",
            content="Text must not be empty.",
        )

    if ctx.database is None:
        return SkillResult(
            status="failed",
            content="Database not available for append_session_state.",
        )

    try:
        updated = ctx.database.append_session_state(
            ctx.session_id,
            section,
            text,
        )
    except Exception as exc:
        return SkillResult(
            status="failed",
            content=f"Failed to append session state: {exc}",
        )

    values: list[str] = getattr(updated, section, [])
    label = _SECTION_LABELS.get(section, section)
    return SkillResult(
        status="success",
        content=(f"Appended to {label} (now {len(values)} entries).\n\n> {text}"),
        artifacts={
            "section": section,
            "entry_count": len(values),
        },
    )


# ── Register ──────────────────────────────────────────────────────────

from harness_poc.system_tools import register as _register  # noqa: E402

_register(
    name="append_session_state",
    description=(
        "Record a finding, decision, open question, or next action into "
        "the session state. This is the agent's scratchpad for tracking "
        "discoveries during task execution. Session state can later be "
        "consolidated into durable project state.\n\n"
        "Sections: notes, decisions, next_actions, open_questions, changelog."
    ),
    parameters={
        "type": "object",
        "properties": {
            "section": {
                "type": "string",
                "description": (
                    "Section to append to: notes, decisions, next_actions, "
                    "open_questions, or changelog."
                ),
            },
            "text": {
                "type": "string",
                "description": "The entry text to record.",
            },
        },
        "required": ["section", "text"],
    },
    handler=append_session_state,
)
