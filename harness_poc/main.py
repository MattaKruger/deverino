from __future__ import annotations

import asyncio

from harness_poc.app_factory import build_app_state
from harness_poc.cli import app
from harness_poc.core.processors.circuit_breaker import run_circuit_breaker
from harness_poc.core.processors.llm_worker import run_llm_worker
from harness_poc.core.processors.tool_worker import run_skill_worker


async def run_async_main(session_id: str | None = None) -> None:
    app_state = build_app_state()
    effective_session_id = session_id or app_state.session_id

    await asyncio.gather(
        run_circuit_breaker(
            app_state.event_bus,
            effective_session_id,
            max_retries=app_state.config.runtime.max_retries,
            max_tokens=app_state.config.runtime.max_tokens,
        ),
        run_llm_worker(
            app_state.event_bus,
            effective_session_id,
            app_state.database,
            app_state.config,
            app_state.skill_runner,
        ),
        run_skill_worker(
            app_state.event_bus,
            effective_session_id,
            app_state.skill_runner,
        ),
    )


def main() -> None:
    app()


if __name__ == "__main__":
    main()
