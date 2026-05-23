from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from harness_poc.core.runtime.message_history import estimate_message_tokens

if TYPE_CHECKING:
    from pydantic_ai.messages import ModelMessage

    from harness_poc.core.runtime.llm_client import Usage


@dataclass(frozen=True, slots=True)
class TokenAccounting:
    input_tokens: int
    output_tokens: int
    billable_tokens: int
    new_tokens: int


def account_for_model_run(
    usage: Usage | None,
    *,
    new_messages: list[ModelMessage] | None = None,
    fallback_new_tokens: int = 0,
) -> TokenAccounting:
    input_tokens = int((usage or {}).get("prompt_tokens", 0))
    output_tokens = int((usage or {}).get("completion_tokens", 0))
    billable_tokens = int((usage or {}).get("total_tokens", input_tokens + output_tokens))

    if new_messages:
        new_tokens = estimate_message_tokens(new_messages)
    elif fallback_new_tokens > 0:
        new_tokens = fallback_new_tokens
    else:
        new_tokens = output_tokens

    return TokenAccounting(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        billable_tokens=billable_tokens,
        new_tokens=new_tokens,
    )
