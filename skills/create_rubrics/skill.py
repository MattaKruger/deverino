"""Generate benchmark rubric .md files from natural-language descriptions."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from pydantic import BaseModel, Field
from pydantic_ai import Agent, PromptedOutput

from harness_poc.core.runtime import build_model, is_live_model
from harness_poc.core.skills import SkillContext, SkillResult

if TYPE_CHECKING:
    from pydantic_ai.models import Model

DRAFT_KEY_PREFIX = "rubric_draft"
RUBRICS_DIR = Path("tests/bench/rubrics")
DEFAULT_JUDGE_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_THRESHOLD = 0.7
MAX_SLUG_SOURCE_LENGTH = 80

# ---------------------------------------------------------------------------
# Structured output model for LLM extraction
# ---------------------------------------------------------------------------


class ExtractedGates(BaseModel):
    """Structured extraction of rubric gates from a natural-language description."""

    must_contain: list[str] = Field(
        default_factory=list,
        description="Exact quoted phrases the agent's answer MUST contain",
    )
    must_not_contain: list[str] = Field(
        default_factory=list,
        description="Exact quoted phrases the agent's answer must NOT contain",
    )
    min_words: int | None = Field(
        default=None,
        description="Minimum word count for the answer, or null if not applicable",
    )
    skill_sequence: list[str] | None = Field(
        default=None,
        description="Skills the agent should call, in expected order, or null",
    )
    judge_prompt: str = Field(
        ...,
        description=(
            "Scoring prompt for an LLM judge. Describe what 'good' means for this "
            "scenario. Must end with 'Answer: {answer}' on its own line so the "
            "benchmark runner can substitute the agent's output."
        ),
    )


# ---------------------------------------------------------------------------
# Extraction system prompt
# ---------------------------------------------------------------------------

EXTRACTION_SYSTEM_PROMPT = """\
You extract structured benchmark assertions from natural-language descriptions
of expected agent behaviour.

Given a description of what an agent should do and a goal string, extract:

- must_contain: exact phrases the answer MUST contain. Use the exact wording
  from the description when possible. These become hard assertion gates.
- must_not_contain: exact phrases the answer must NOT contain (e.g. "I don't
  know", hallucinated paths, evasion language).
- min_words: a minimum word count if the description implies a substantive
  answer is needed. Omit (null) for trivial answers.
- skill_sequence: skills the agent should call, in expected order. Use actual
  skill names from the harness (read_memory, semble_search, web_search,
  delegate_task, etc.). Omit (null) if no specific skill sequence is described.
- judge_prompt: a scoring prompt for a separate LLM judge. Describe what
  "good" means for this specific scenario — what makes an answer high quality
  vs low quality. Be specific enough that a judge can assign a 0.0-1.0 score.
  The prompt MUST end with this exact line:

  Answer: {answer}

Rules:
- must_contain and must_not_contain values MUST be exact quoted strings, not
  paraphrases or descriptions. They will be used for literal substring matching.
- If the description does not mention a particular gate type, leave it empty
  or null — do not invent constraints.
- The judge_prompt should focus on semantic quality: accuracy, completeness,
  relevance. Not mechanical checks like word count or substring presence
  (those are covered by hard gates)."""


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def execute(ctx: SkillContext, arguments: dict[str, Any]) -> SkillResult:
    description = str(arguments.get("description") or "").strip()
    goal = str(arguments.get("goal") or "").strip()
    slug = str(arguments.get("slug") or "").strip()
    confirm = bool(arguments.get("confirm", False))
    judge_model = str(arguments.get("model") or DEFAULT_JUDGE_MODEL).strip()
    threshold = _parse_threshold(arguments.get("threshold", DEFAULT_THRESHOLD))

    if confirm:
        return _confirm_and_write(ctx, slug)

    if not description:
        return SkillResult(
            status="blocked",
            content="Missing required parameter: description",
        )
    if not goal:
        return SkillResult(
            status="blocked",
            content="Missing required parameter: goal",
        )

    if not slug:
        slug = _slugify(description, goal)

    model = build_model(ctx.config.llm)
    if not is_live_model(model):
        return SkillResult(
            status="blocked",
            content=(
                "No live LLM is available for rubric extraction. "
                "Check your provider credentials and LLM configuration."
            ),
        )

    try:
        gates = _extract_gates(description, goal, model)
    except Exception as exc:  # noqa: BLE001
        return SkillResult(
            status="failed",
            content=f"LLM extraction failed: {exc}",
        )

    rubric_md = _format_rubric(slug, goal, gates, judge_model, threshold)

    draft_key = f"{DRAFT_KEY_PREFIX}:{slug}"
    ctx.database.write_memory(
        ctx.session_id,
        draft_key,
        {
            "rubric_md": rubric_md,
            "slug": slug,
            "goal": goal,
            "judge_model": judge_model,
            "threshold": threshold,
            "gates": gates.model_dump(),
        },
    )

    return SkillResult(
        status="needs_orchestrator_action",
        content=rubric_md,
        artifacts={
            "slug": slug,
            "draft_key": draft_key,
            "action": (
                f"Review the rubric above. To persist, run: "
                f'/skill create_rubrics confirm=true slug="{slug}"'
            ),
        },
    )


# ---------------------------------------------------------------------------
# Confirmation: write draft to disk
# ---------------------------------------------------------------------------


def _confirm_and_write(ctx: SkillContext, slug: str) -> SkillResult:
    if not slug:
        return SkillResult(
            status="blocked",
            content="Slug is required when confirming. Provide the slug from the preview step.",
        )

    draft_key = f"{DRAFT_KEY_PREFIX}:{slug}"
    draft = ctx.database.read_memory(ctx.session_id, draft_key)

    if not isinstance(draft, dict) or "rubric_md" not in draft:
        return SkillResult(
            status="blocked",
            content=(
                f"No draft found for slug '{slug}'. "
                "Run create_rubrics without confirm first to generate a draft."
            ),
        )

    rubric_md = str(draft["rubric_md"])
    rubrics_dir = ctx.project_root / RUBRICS_DIR
    rubrics_dir.mkdir(parents=True, exist_ok=True)

    rubric_path = rubrics_dir / f"{slug}.md"
    if rubric_path.exists():
        return SkillResult(
            status="blocked",
            content=(
                f"Rubric file already exists: {rubric_path}\n"
                f"Choose a different slug to avoid overwriting."
            ),
        )

    rubric_path.write_text(rubric_md, encoding="utf-8")

    # Clean up draft
    ctx.database.write_memory(ctx.session_id, draft_key, {})

    relative_path = rubric_path.relative_to(ctx.project_root)
    return SkillResult(
        status="success",
        content=f"Rubric written to {relative_path}",
        artifacts={
            "slug": slug,
            "path": str(relative_path),
        },
    )


# ---------------------------------------------------------------------------
# LLM extraction
# ---------------------------------------------------------------------------


def _extract_gates(description: str, goal: str, model: Model) -> ExtractedGates:
    """Call the LLM with structured output to extract rubric gates."""
    agent = Agent(
        model,
        output_type=PromptedOutput(
            ExtractedGates,
            name="extracted_gates",
            description="Structured rubric gates extracted from the behaviour description.",
        ),
        system_prompt=EXTRACTION_SYSTEM_PROMPT,
        output_retries=1,
    )

    user_prompt = (
        f"Description of expected agent behaviour:\n\n{description}\n\n"
        f"Goal the agent will be given:\n\n{goal}"
    )

    result = agent.run_sync(user_prompt)
    return cast("ExtractedGates", result.output)


# ---------------------------------------------------------------------------
# Rubric formatting
# ---------------------------------------------------------------------------


def _format_rubric(
    slug: str,
    goal: str,
    gates: ExtractedGates,
    judge_model: str,
    threshold: float,
) -> str:
    """Render extracted gates into the .md format parsed by rubric_loader.py."""
    lines: list[str] = []
    lines.append(f"# Rubric: {slug}")
    lines.append("")
    lines.append("## Goal")
    lines.append("")
    lines.append(goal)
    lines.append("")

    lines.append("## Hard Assertions")
    lines.append("")
    lines.extend(f'- must_contain: "{f}"' for f in gates.must_contain)
    lines.extend(f'- must_not_contain: "{f}"' for f in gates.must_not_contain)
    if gates.min_words is not None:
        lines.append(f"- min_words: {gates.min_words}")
    if gates.skill_sequence:
        skills = ", ".join(gates.skill_sequence)
        lines.append(f"- skill_sequence: [{skills}]")
    lines.append("")

    lines.append("## LLM Judge")
    lines.append("")
    lines.append(f"threshold: {threshold}")
    lines.append(f"model: {judge_model}")
    lines.append("prompt: |")
    lines.extend(f"  {line}" for line in gates.judge_prompt.splitlines())

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _slugify(description: str, goal: str = "") -> str:
    """Generate a filename-safe slug from a description and optional goal.

    Prefers the goal as slug source if it's short enough; falls back to
    the description. Strips non-alphanumeric characters and collapses
    whitespace to hyphens.
    """
    source = goal if goal and len(goal) <= MAX_SLUG_SOURCE_LENGTH else description
    # Take first ~80 chars to keep slugs reasonable
    source = source[:MAX_SLUG_SOURCE_LENGTH].strip()

    # Lowercase and replace non-alphanumeric sequences with hyphens
    slug = re.sub(r"[^a-z0-9]+", "-", source.lower()).strip("-")

    # Collapse repeated hyphens
    slug = re.sub(r"-{2,}", "-", slug)

    return slug or "rubric"


def _parse_threshold(value: object) -> float:
    """Parse threshold with a floor of 0.0 and ceiling of 1.0."""
    try:
        parsed = float(str(value))
    except (ValueError, TypeError):
        return DEFAULT_THRESHOLD
    return max(0.0, min(1.0, parsed))
