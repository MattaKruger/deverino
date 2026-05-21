from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from harness_poc.core.processors.circuit_breaker import run_circuit_breaker
from harness_poc.core.processors.llm_worker import run_llm_worker
from harness_poc.core.processors.tool_worker import run_skill_worker

if TYPE_CHECKING:
    from harness_poc.app_factory import Identity, Runtime

logger = logging.getLogger(__name__)

_STOP_TIMEOUT_S = 5.0


class ProcessorSupervisor:
    def __init__(self, identity: Identity) -> None:
        self._identity = identity
        self._tasks: list[asyncio.Task[None]] = []
        self._in_flight_calls: dict[str, str] = {}

    async def start(self, runtime: Runtime) -> None:
        if self._tasks:
            msg = "Supervisor already started"
            raise RuntimeError(msg)

        bus = self._identity.event_bus
        session_id = self._identity.session_id
        database = self._identity.database

        self._tasks = [
            asyncio.create_task(
                run_circuit_breaker(
                    bus,
                    session_id,
                    max_retries=runtime.config.runtime.max_retries,
                    max_tokens=runtime.config.runtime.max_tokens,
                ),
                name="circuit_breaker",
            ),
            asyncio.create_task(
                run_llm_worker(
                    bus,
                    session_id,
                    database,
                    runtime.config,
                    runtime.skill_runner,
                ),
                name="llm_worker",
            ),
            asyncio.create_task(
                run_skill_worker(
                    bus,
                    session_id,
                    runtime.skill_runner,
                    on_call_started=self._record_call_started,
                    on_call_ended=self._record_call_ended,
                ),
                name="tool_worker",
            ),
        ]

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()

        for task in self._tasks:
            try:
                await asyncio.wait_for(task, timeout=_STOP_TIMEOUT_S)
            except (TimeoutError, asyncio.CancelledError):
                logger.warning("Processor %s did not exit cleanly", task.get_name())
            except Exception:
                logger.exception("Processor %s exited with an error", task.get_name())

        self._tasks = []
        self._in_flight_calls.clear()

    async def restart(self, runtime: Runtime) -> None:
        await self.stop()
        await self.start(runtime)

    def cancel_in_flight(self, runtime: Runtime, reason: str) -> list[tuple[str, str]]:
        calls = self.in_flight()
        for call_id, _skill_name in calls:
            runtime.skill_runner.cancel_call(call_id, reason)
            runtime.tool_runner.cancel_call(call_id, reason)
        return calls

    def in_flight(self) -> list[tuple[str, str]]:
        return list(self._in_flight_calls.items())

    def _record_call_started(self, call_id: str, skill_name: str) -> None:
        self._in_flight_calls[call_id] = skill_name

    def _record_call_ended(self, call_id: str) -> None:
        self._in_flight_calls.pop(call_id, None)
