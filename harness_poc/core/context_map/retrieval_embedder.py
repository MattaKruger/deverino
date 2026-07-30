"""RetrievalEmbedder — lazy-loads BAAI/bge-base-en-v1.5 for semantic corpus retrieval.

Separate from copt_gate.py (all-MiniLM-L6-v2, 384-dim, for dedup) and
embedder.py (Snowflake arctic-embed-l, 1024-dim, for Vespa document retrieval).
Uses TextEmbedder with an explicit model_name override.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from harness_poc.core.retrieval.embedder import TextEmbedder

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

_BGE_MODEL = "BAAI/bge-base-en-v1.5"
_BGE_DIM = 768


class RetrievalEmbedder:
    """Thread-safe lazy-loading wrapper around bge-base-en-v1.5.

    Uses the shared TextEmbedder module-level cache (keyed by model_name + device)
    so multiple RetrievalEmbedder instances reuse the same loaded model.
    """

    def __init__(self, model_name: str = _BGE_MODEL) -> None:
        self._embedder = TextEmbedder(model_name=model_name)

    @property
    def dim(self) -> int:
        return _BGE_DIM

    def embed_query(self, text: str) -> list[float]:
        """Embed a single query string. Returns a 768-dim normalized vector."""
        return self._embedder.embed_single(text)

    def embed_entries(self, summaries: list[str]) -> list[list[float]]:
        """Embed a batch of entry summaries. Returns one 768-dim vector per summary."""
        if not summaries:
            return []
        vectors = self._embedder.embed_batch(summaries)
        return [v.tolist() for v in vectors]
