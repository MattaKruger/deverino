from __future__ import annotations

import asyncio

from harness_poc.app_factory import build_app_state
from harness_poc.cli import app


async def run_async_main(session_id: str | None = None) -> None:
    app_state = build_app_state(session_id=session_id)
    await app_state.long_lived.supervisor.start(app_state.runtime)
    materializer_task = asyncio.create_task(
        app_state.long_lived.materializer_runner.run_forever(),
        name="materializer",
    )
    try:
        await materializer_task
    finally:
        await app_state.long_lived.supervisor.stop()


def main() -> None:
    app()


if __name__ == "__main__":
    main()
