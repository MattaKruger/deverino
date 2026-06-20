"""GPU-accelerated text embedding via sentence-transformers.

Provides a caching embedder that lazily loads a SentenceTransformer model on first use,
defaulting to the GPU (CUDA) when available.  All public methods are thread-safe once
the model is loaded.

With jina-embeddings-v3 (the default), ``embed_query`` encodes search queries
using the ``retrieval.query`` LoRA adapter, while ``embed_batch`` encodes
document chunks using ``retrieval.passage``.
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from collections.abc import Sequence

    from numpy.typing import NDArray

logger = logging.getLogger(__name__)

# snowflake-arctic-embed-l-v2.0 produces 1024-dim vectors, trained with CLS pooling.
# Multilingual (74 languages), MRL support (truncatable to 256-dim), 8192 token context.
DEFAULT_MODEL = "Snowflake/snowflake-arctic-embed-l-v2.0"
DEFAULT_DIM = 1024
DEFAULT_DEVICE = "cuda"  # falls back to "cpu" when CUDA is unavailable

# Module-level cache: model loaded once, reused across TextEmbedder instances.
# Keyed by (model_name, device) to support multiple configurations if needed.
_model_cache: dict[tuple[str, str], object] = {}
_cache_lock = threading.Lock()


class TextEmbedder:
    """Lazy-loading wrapper around SentenceTransformer.

    Typical usage::

        embedder = TextEmbedder()
        vectors = embedder.embed_batch(["hello world", "foo bar"])
        # vectors.shape == (2, 1024)
    """

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        device: str | None = None,
    ) -> None:
        """Configure the embedder without loading the model.

        Args:
            model_name: HuggingFace model identifier or local path.
            device: Torch device string (e.g. ``"cuda"``, ``"cpu"``).
                    Defaults to ``"cuda"`` when available, else ``"cpu"``.
        """
        self._model_name = model_name
        self._device = device
        self._lock = threading.Lock()
        self._model: object | None = None  # SentenceTransformer after lazy load

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def dim(self) -> int:
        """Return the embedding dimension (hard-coded for the default model)."""
        # jina-embeddings-v3 -> 1024 by default (MRL supports 32-1024).
        return DEFAULT_DIM

    @property
    def device(self) -> str:
        """Return the torch device this embedder is configured to use."""
        if self._device is not None:
            return self._device
        try:
            import torch  # noqa: PLC0415

            return "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            return "cpu"

    @property
    def model(self) -> object:
        """Return the underlying SentenceTransformer, loading it on first access.

        Uses a module-level cache so that creating multiple TextEmbedder
        instances reuses the already-loaded model rather than reloading.

        The heavy ``_load_model()`` call runs *outside* ``_cache_lock`` so
        that concurrent threads (e.g. a background preloader and a foreground
        search) don't serialize on the 20 s HuggingFace download.
        """
        if self._model is not None:
            return self._model
        cache_key = (self._model_name, self.device)
        with _cache_lock:
            cached = _model_cache.get(cache_key)
            if cached is not None:
                self._model = cached
                return cached
        # Load outside the lock so other threads aren't blocked.
        loaded = self._load_model()
        with _cache_lock:
            # Another thread may have beaten us — check again.
            cached = _model_cache.get(cache_key)
            if cached is not None:
                self._model = cached
                return cached  # discard ours, use the winner
            _model_cache[cache_key] = loaded
            self._model = loaded
        return loaded

    def embed_batch(
        self,
        texts: Sequence[str],
        *,
        prompt_name: str | None = None,
    ) -> NDArray[np.float32]:
        """Encode a batch of texts, returning a float32 array of shape ``(N, dim)``.

        For jina-embeddings-v3, document passages should use
        ``prompt_name="retrieval.passage"``. When *prompt_name* is None,
        no task-specific prompt or LoRA adapter is applied.
        """
        if not texts:
            return np.empty((0, self.dim), dtype=np.float32)
        model = self.model
        encode_kwargs: dict[str, object] = {
            "batch_size": 32,
            "show_progress_bar": False,
            "convert_to_numpy": True,
            "normalize_embeddings": True,
        }
        if prompt_name is not None:
            encode_kwargs["prompt_name"] = prompt_name
        # SentenceTransformer.encode returns a numpy array.
        embeddings: NDArray[np.float32] = model.encode(  # ty: ignore
            list(texts),
            **encode_kwargs,  # type: ignore[arg-type]
        )
        return embeddings

    def embed_query(self, text: str) -> list[float]:
        """Encode a search query using the retrieval.query LoRA adapter.

        This is the companion to ``embed_batch(..., prompt_name="retrieval.passage")``.
        """
        vec: NDArray[np.float32] = self.embed_batch([text], prompt_name="retrieval.query")[0]
        return vec.tolist()

    def embed_single(self, text: str) -> list[float]:
        """Encode a single text to a Python list of floats.

        Uses no task-specific prompt. Prefer ``embed_query`` for search queries
        when using a task-LoRA model like jina-embeddings-v3.
        """
        vec: NDArray[np.float32] = self.embed_batch([text])[0]
        return vec.tolist()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load_model(self) -> object:
        """Import and instantiate SentenceTransformer on the chosen device."""
        from sentence_transformers import SentenceTransformer  # noqa: PLC0415

        device = self.device
        logger.info("Loading embedding model %r on %s ...", self._model_name, device)
        model = SentenceTransformer(
            self._model_name,
            device=device,
            trust_remote_code=True,
        )
        # Switch to fp16 for GPU to get ~3x throughput vs fp32.
        if device == "cuda":
            model.half()
            logger.info("Embedding model converted to fp16 for GPU inference.")
        logger.info("Embedding model %r ready on %s.", self._model_name, device)
        return model


def preload_embedder() -> None:
    """Preload the embedding model so the first search is fast.

    The default embedding model (~20 s cold-start download from HuggingFace)
    is loaded eagerly and cached in the module-level ``_model_cache`` so
    that the first ``search_documents`` call doesn't time out.
    """
    logger.info("Preloading embedding model (background)...")
    embedder = TextEmbedder()
    embedder.model  # trigger lazy load
    logger.info("Embedding model ready.")
