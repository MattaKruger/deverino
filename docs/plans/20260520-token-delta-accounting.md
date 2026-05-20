# Token Delta Accounting Spec

## Problem

The harness currently reports token totals by summing provider `total_tokens` after every model
call. Provider totals include the full prompt context sent on that call, so retained conversation
history is counted again on every turn. This makes the REPL/TUI header, session state, and goal
runner totals look like context growth is much larger than it actually is.

## Requirements

- Track retained-context growth separately from provider-reported usage.
- Keep provider usage available for cost-oriented reporting.
- Preserve compatibility for existing `LLMActionEmitted.tokens_used` consumers.
- Apply the same accounting definitions in chat, background LLM worker, session reducers, circuit
  breaker, and goal runner.
- Avoid network/model calls in tests.

## Definitions

- `input_tokens`: provider-reported prompt/input tokens for one model call.
- `output_tokens`: provider-reported completion/output tokens for one model call.
- `billable_tokens`: provider-reported total for one model call, usually input plus output.
- `new_tokens`: estimated tokens newly added to retained harness context by this turn.
- `tokens_used`: compatibility field; now stores `new_tokens`.

## Design

For Pydantic AI chat/runtime calls, compute `new_tokens` from `result.new_messages()` because those
are exactly the messages appended to retained history. When a fake or fallback runtime does not
return messages, estimate the synthetic user/assistant exchange that the REPL appends. If neither
is available, fall back to output tokens.

For goal runs, stop adding the full rebuilt decision context every iteration. Track the previous
context estimate and add only positive context growth plus the model's output tokens.

## Acceptance Criteria

- A chat turn with `prompt_tokens=100`, `completion_tokens=10`, and new retained messages estimated
  at 20 tokens publishes `tokens_used=20` and `billable_tokens=110`.
- Existing events created with only `tokens_used` still validate and treat that value as billable
  when no explicit `billable_tokens` is present.
- Session snapshots and circuit breaker totals continue summing `tokens_used`, now meaning
  retained-context growth.
- Goal runner token totals no longer repeatedly add unchanged prompt context across iterations.
- Focused pytest coverage proves the new accounting behavior.
