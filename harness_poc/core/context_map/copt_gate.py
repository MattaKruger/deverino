"""CopT gate embedding helper — lazy-loads all-MiniLM-L6-v2 for semantic dedup.

See plans/09-copt-gate-plan.md for the full design.
"""

from __future__ import annotations

import logging
from threading import Lock
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

_MODEL_NAME = "all-MiniLM-L6-v2"
_EMBEDDING_DIM = 384
_model: SentenceTransformer | None = None
_lock = Lock()


def get_embedding_model() -> SentenceTransformer:
    """Return the shared, lazily-loaded MiniLM embedding model.

    Thread-safe: the first caller loads the model; subsequent callers
    reuse the cached instance. The model runs on CPU (~2ms per short string).
    """
    global _model  # noqa: PLW0603
    if _model is not None:
        return _model
    with _lock:
        if _model is not None:
            return _model
        from sentence_transformers import SentenceTransformer  # noqa: PLC0415

        logger.info("Loading embedding model: %s", _MODEL_NAME)
        _model = SentenceTransformer(_MODEL_NAME)
        return _model


def embed_summaries(summaries: list[str]) -> list[list[float]]:
    """Embed a batch of summary strings.

    Returns a list of 384-dim float vectors in the same order.
    """
    if not summaries:
        return []
    model = get_embedding_model()
    embeddings = model.encode(summaries, normalize_embeddings=True)
    return [emb.tolist() for emb in embeddings]  # type: ignore[union-attr]


def embed_single(summary: str) -> list[float]:
    """Embed a single summary string. Returns a 384-dim float vector."""
    model = get_embedding_model()
    embedding = model.encode([summary], normalize_embeddings=True)
    return embedding[0].tolist()  # type: ignore[union-attr]
