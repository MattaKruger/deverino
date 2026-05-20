from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from harness_poc.core.config import HarnessConfig
    from harness_poc.core.database import BlackboardDatabase
    from harness_poc.core.skill_runner import SkillRunner

logger = logging.getLogger(__name__)


class MaterializerRunner:
    def __init__(
        self,
        db: BlackboardDatabase,
        skill_runner: SkillRunner,
        config: HarnessConfig,
        poll_interval: float = 30.0,
    ) -> None:
        self._db = db
        self._skill_runner = skill_runner
        self._config = config
        self._poll_interval = poll_interval

    async def run_forever(self) -> None:
        while True:
            try:
                await self._poll_once()
            except Exception:
                logger.exception("MaterializerRunner: unhandled error in poll cycle")
            await asyncio.sleep(self._poll_interval)

    async def _poll_once(self) -> None:
        corpus_keys = self._db.get_pending_corpus_keys()
        for corpus_key in corpus_keys:
            await self._materialize(corpus_key)

    async def _materialize(self, corpus_key: str) -> None:
        result = await asyncio.to_thread(
            self._skill_runner.execute_skill,
            "context-map-materializer",
            {
                "corpus_key": corpus_key,
                "max_event_tokens": self._config.runtime.materializer_max_event_tokens,
                "token_budget": self._config.runtime.materializer_token_budget,
            },
            "materializer",
        )
        if result.status != "success":
            logger.warning("Materializer failed for %s: %s", corpus_key, result.content)
