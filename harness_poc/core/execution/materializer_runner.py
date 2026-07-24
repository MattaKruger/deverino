from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from harness_poc.app_factory import Runtime
    from harness_poc.core.config import HarnessConfig
    from harness_poc.core.skills import SkillRunner
    from harness_poc.core.storage import BlackboardDatabase

logger = logging.getLogger(__name__)


class MaterializerRunner:
    def __init__(
        self,
        db: BlackboardDatabase,
        skill_runner: SkillRunner,
        config: HarnessConfig,
        session_id: str,
        poll_interval: float = 30.0,
    ) -> None:
        self._db = db
        self._skill_runner = skill_runner
        self._config = config
        self._session_id = session_id
        self._poll_interval = poll_interval
        self._no_change_count: dict[str, int] = {}

    def swap_runtime(self, runtime: Runtime) -> None:
        """Replace reloadable runtime references while preserving materializer state."""
        self._skill_runner = runtime.skill_runner
        self._config = runtime.config

    async def run_forever(self) -> None:
        while True:
            try:
                await self._poll_once()
            except Exception:
                logger.exception("MaterializerRunner: unhandled error in poll cycle")
            await asyncio.sleep(self._poll_interval)

    async def _poll_once(self) -> None:
        corpus_keys = self._db.get_pending_corpus_keys()
        now = datetime.now(tz=UTC).isoformat(timespec="seconds")
        for corpus_key in corpus_keys:
            if self._db.is_map_frozen(corpus_key, now):
                continue
            await self._materialize(corpus_key)

    async def _materialize(self, corpus_key: str) -> None:
        result = await asyncio.to_thread(
            self._skill_runner.execute_skill,
            "context-map-materializer",
            {
                "corpus_key": corpus_key,
                "max_event_tokens": self._config.runtime.materializer_max_event_tokens,
                "session_id": self._session_id,
            },
            "materializer",
        )
        if result.status != "success":
            logger.warning("Materializer failed for %s: %s", corpus_key, result.content)
            return

        map_changed = bool(result.artifacts.get("map_changed", True))
        if map_changed:
            self._no_change_count[corpus_key] = 0
            # Post-write hook: embed entries for semantic retrieval
            with suppress(Exception):
                self._embed_retrieval_vectors(corpus_key)
            return

        self._no_change_count[corpus_key] = self._no_change_count.get(corpus_key, 0) + 1
        threshold = self._config.runtime.materializer_freeze_threshold
        if self._no_change_count[corpus_key] < threshold:
            return

        freeze_until = (
            datetime.now(tz=UTC)
            + timedelta(seconds=self._config.runtime.materializer_freeze_seconds)
        ).isoformat(timespec="seconds")
        self._db.set_map_freeze(corpus_key, freeze_until)
        logger.info("Froze map for %s until %s", corpus_key, freeze_until)

    def _embed_retrieval_vectors(self, corpus_key: str) -> None:
        """Embed materialized map entries with bge for semantic retrieval.

        Best-effort: failures are logged at DEBUG and do not affect
        materialization. Only runs when semantic retrieval is enabled.
        """
        with suppress(Exception):
            entries = self._db.get_context_map(corpus_key) or []
            if not entries:
                return

            from harness_poc.core.context_map.retrieval_embedder import RetrievalEmbedder  # noqa: PLC0415, I001

            embedder = RetrievalEmbedder()
            summaries = [e.summary for e in entries]
            vectors = embedder.embed_entries(summaries)

            entry_vectors = [
                (e.entry_id.replace("-", ""), v)
                for e, v in zip(entries, vectors, strict=True)
            ]
            self._db.retrieval_upsert_embeddings(corpus_key, entry_vectors)
