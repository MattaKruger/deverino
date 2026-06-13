"""Rubric — portable, human-readable .md specification of expected agent behavior."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from harness_poc.core.config import LLMConfig
    from harness_poc.core.events import BaseEvent
    from harness_poc.core.runtime import GoalRunResult


# ---------------------------------------------------------------------------
# Rubric dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Rubric:
    """A portable specification of expected agent behavior.

    Loaded from a .md file. Defines hard gates (deterministic, free)
    and an optional LLM judge (quality scoring). The same rubric can
    validate a mock-LLM session (hard gates only) or a live-LLM
    benchmark (hard gates + LLM judge).
    """

    slug: str
    goal: str
    must_contain: list[str] = field(default_factory=list)
    must_not_contain: list[str] = field(default_factory=list)
    min_words: int | None = None
    skill_sequence: list[str] | None = None
    judge_threshold: float | None = None
    judge_model: str | None = None
    judge_prompt: str | None = None

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    @classmethod
    def from_markdown(cls, path: Path) -> Rubric:
        """Parse a rubric .md file.

        Expected format:

            # Rubric: <slug>

            ## Goal

            <goal text>

            ## Hard Assertions

            - must_contain: "<fragment>"
            - must_not_contain: "<fragment>"
            - min_words: <int>
            - skill_sequence: [skill_a, skill_b, ...]

            ## LLM Judge

            threshold: <float>
            model: <model-id>
            prompt: |
              <scoring prompt with {answer} placeholder>
        """
        text = path.read_text(encoding="utf-8")
        slug = _extract_slug(text, path)
        sections = _split_sections(text)

        goal = sections.get("Goal", "").strip()
        hard_text = sections.get("Hard Assertions", "")
        judge_text = sections.get("LLM Judge", "")

        must_contain, must_not_contain, min_words, skill_sequence = _parse_hard_assertions(
            hard_text
        )
        threshold, model, prompt = _parse_judge_section(judge_text)

        return cls(
            slug=slug,
            goal=goal,
            must_contain=must_contain,
            must_not_contain=must_not_contain,
            min_words=min_words,
            skill_sequence=skill_sequence,
            judge_threshold=threshold,
            judge_model=model,
            judge_prompt=prompt,
        )

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def assert_hard_gates(
        self,
        result: GoalRunResult,
        events: list[BaseEvent] | None = None,
    ) -> None:
        """Run all hard (deterministic, free) assertions against a session result.

        Args:
            result: The GoalRunResult from a completed session.
            events: Optional event trace for skill_sequence validation.
                When None, skill_sequence is skipped. Pass
                live_session.events (benchmarks) or harness.all_events
                (agent tests) to enable process validation.

        """
        content_lower = result.content.lower()

        for fragment in self.must_contain:
            if fragment.lower() not in content_lower:
                msg = (
                    f"Rubric '{self.slug}': expected answer to contain "
                    f"'{fragment}', but it was missing.\n"
                    f"Answer: {result.content[:300]}"
                )
                raise AssertionError(msg)

        for fragment in self.must_not_contain:
            if fragment.lower() in content_lower:
                msg = (
                    f"Rubric '{self.slug}': answer must NOT contain "
                    f"'{fragment}', but it was found.\n"
                    f"Answer: {result.content[:300]}"
                )
                raise AssertionError(msg)

        if self.min_words is not None:
            word_count = len(result.content.split())
            if word_count < self.min_words:
                msg = (
                    f"Rubric '{self.slug}': expected at least {self.min_words} words, "
                    f"got {word_count}.\n"
                    f"Answer: {result.content[:300]}"
                )
                raise AssertionError(msg)

        if self.skill_sequence and events is not None:
            from tests.helpers import TraceAssertions

            TraceAssertions(events).assert_skill_order(*self.skill_sequence)

    def judge(self, answer: str, *, config: LLMConfig) -> float | None:
        """Run the LLM judge. Returns None if no judge is configured.

        The judge model scores the answer 0.0-1.0 against the rubric's
        quality prompt. Requires a real LLM — no mock support.

        Args:
            answer: The agent's output to evaluate.
            config: Harness LLM config for provider/api-key resolution.

        """
        if self.judge_prompt is None or self.judge_model is None:
            return None
        from tests.bench.llm_judge import llm_judge

        return llm_judge(
            self.judge_prompt,
            answer,
            model_id=self.judge_model,
            config=config,
        )


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _extract_slug(text: str, path: Path) -> str:
    """Extract rubric slug from the H1 heading or fall back to filename stem."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(("# Rubric:", "# Rubric ")):
            slug = stripped.split(":", 1)[-1].strip()
            if slug:
                return slug
    return path.stem


def _split_sections(text: str) -> dict[str, str]:
    """Split markdown text by ## headings into a {heading: body} dict."""
    sections: dict[str, str] = {}
    current_heading: str | None = None
    current_body: list[str] = []

    for line in text.splitlines():
        if line.startswith("## "):
            if current_heading is not None:
                sections[current_heading] = "\n".join(current_body)
            current_heading = line[3:].strip()
            current_body = []
        elif current_heading is not None:
            current_body.append(line)

    if current_heading is not None:
        sections[current_heading] = "\n".join(current_body)

    return sections


def _parse_hard_assertions(
    text: str,
) -> tuple[list[str], list[str], int | None, list[str] | None]:
    """Parse the Hard Assertions section.

    Returns (must_contain, must_not_contain, min_words, skill_sequence).
    """
    must_contain: list[str] = []
    must_not_contain: list[str] = []
    min_words: int | None = None
    skill_sequence: list[str] | None = None

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("- "):
            continue
        directive = stripped[2:]  # strip the "- " prefix

        if m := re.match(r'must_contain:\s*"(.+)"$', directive):
            must_contain.append(m.group(1))
        elif m := re.match(r"must_contain:\s*(.+)$", directive):
            # Unquoted fallback
            must_contain.append(m.group(1).strip())

        elif m := re.match(r'must_not_contain:\s*"(.+)"$', directive):
            must_not_contain.append(m.group(1))
        elif m := re.match(r"must_not_contain:\s*(.+)$", directive):
            must_not_contain.append(m.group(1).strip())

        elif m := re.match(r"min_words:\s*(\d+)", directive):
            min_words = int(m.group(1))

        elif m := re.match(r"skill_sequence:\s*\[(.+)\]", directive):
            # Parse [skill_a, skill_b, ...] into a list of strings
            inner = m.group(1)
            skill_sequence = [s.strip().strip("'\"") for s in inner.split(",") if s.strip()]

    return must_contain, must_not_contain, min_words, skill_sequence


def _parse_judge_section(
    text: str,
) -> tuple[float | None, str | None, str | None]:
    """Parse the LLM Judge section.

    Returns (threshold, model, prompt).
    """
    threshold: float | None = None
    model: str | None = None
    prompt_lines: list[str] = []
    in_prompt = False

    for line in text.splitlines():
        stripped = line.strip()

        if in_prompt:
            prompt_lines.append(line)
            continue

        if m := re.match(r"threshold:\s*([\d.]+)", stripped):
            threshold = float(m.group(1))
        elif m := re.match(r"model:\s*(.+)", stripped):
            model = m.group(1).strip()
        elif stripped.startswith("prompt: |"):
            in_prompt = True
            # Content after "prompt: |" on the same line? Unlikely but handle
            after_pipe = stripped.split("|", 1)[-1].strip()
            if after_pipe:
                prompt_lines.append(after_pipe)

    prompt = "\n".join(prompt_lines).strip() if prompt_lines else None
    return threshold, model, prompt
