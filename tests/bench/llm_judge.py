"""LLM judge — score an answer 0.0-1.0 using a cheap model."""

from __future__ import annotations

import asyncio
import logging

from pydantic_ai import Agent

from harness_poc.core.config import LLMConfig
from harness_poc.core.pydantic_runtime import build_model

logger = logging.getLogger(__name__)

# Default judge model when not overridden by rubric or env var.
# Chosen for low cost and fast response — scoring doesn't need reasoning depth.
DEFAULT_JUDGE_MODEL = "claude-haiku-4-5-20251001"


def llm_judge(
    prompt: str,
    answer: str,
    *,
    model_id: str,
    config: LLMConfig,
) -> float:
    """Score an answer 0.0-1.0 against a quality prompt.

    Args:
        prompt: Scoring prompt template with {answer} placeholder.
        answer: The agent's output to evaluate.
        model_id: Model to use for judging (e.g., "claude-haiku-4-5-20251001").
        config: The harness LLM config for provider/api-key resolution.
            The judge reuses the same provider and base_url but can use
            a different model (typically cheaper than the agent model).

    Returns:
        A float in [0.0, 1.0].

    Raises:
        ValueError: If the judge model returns unparseable output.

    """
    return asyncio.run(_llm_judge_async(prompt, answer, model_id=model_id, config=config))


async def _llm_judge_async(
    prompt: str,
    answer: str,
    *,
    model_id: str,
    config: LLMConfig,
) -> float:
    """Async implementation — see llm_judge for docs."""
    filled_prompt = prompt.format(answer=answer)

    # Build a judge-specific LLMConfig: same provider/base_url, different model.
    judge_config = LLMConfig(
        provider=config.provider,
        model=model_id,
        base_url=config.base_url,
    )
    judge_model = build_model(judge_config)

    agent = Agent(
        judge_model,
        output_type=float,
        system_prompt=(
            "You are a scoring judge. Read the provided answer and score it "
            "0.0 to 1.0 based on the criteria. Return ONLY the number, "
            "with no explanation, no markdown, no extra text. "
            "Example valid responses: 0.0, 0.5, 0.75, 1.0"
        ),
        output_retries=1,
    )

    try:
        result = await agent.run(filled_prompt)
    except Exception as exc:
        msg = (
            f"LLM judge failed to produce a parseable score from model "
            f"'{model_id}'. Raw error: {exc}"
        )
        raise ValueError(msg) from exc

    score = result.output
    if not isinstance(score, (int, float)):
        msg = (
            f"LLM judge returned non-numeric output from model '{model_id}': "
            f"{score!r} (type={type(score).__name__})"
        )
        raise TypeError(msg)

    # Clamp to [0.0, 1.0] — models occasionally return scores outside range
    clamped = max(0.0, min(1.0, float(score)))
    if clamped != score:
        logger.debug(
            "Judge score clamped: raw=%s → clamped=%s",
            score,
            clamped,
        )

    return clamped
