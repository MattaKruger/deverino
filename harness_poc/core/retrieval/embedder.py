"""GPU-accelerated text embedding via sentence-transformers.

Provides a caching embedder that lazily loads a SentenceTransformer model on first use,
defaulting to the GPU (CUDA) when available.  All public methods are thread-safe once
the model is loaded.
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

# mxbai-embed-large-v1 produces 1024-dim vectors, trained with CLS pooling.
# This is the same model currently used by the Vespa hugging-face-embedder.
DEFAULT_MODEL = "mixedbread-ai/mxbai-embed-large-v1"
DEFAULT_DIM = 1024
DEFAULT_DEVICE = "cuda"  # falls back to "cpu" when CUDA is unavailable


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
        # mxbai-embed-large-v1 -> 1024.  If you switch models, override this.
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
        """Return the underlying SentenceTransformer, loading it on first access."""
        if self._model is None:
            with self._lock:
                if self._model is None:  # double-checked locking
                    self._model = self._load_model()
        return self._model

    def embed_batch(self, texts: Sequence[str]) -> NDArray[np.float32]:
        """Encode a batch of texts, returning a float32 array of shape ``(N, dim)``.

        Texts are passed directly to the model; no prefix is prepended.
        """
        if not texts:
            return np.empty((0, self.dim), dtype=np.float32)
        model = self.model
        # SentenceTransformer.encode returns a numpy array.
        embeddings: NDArray[np.float32] = model.encode(  # type: ignore[union-attr]
            list(texts),
            batch_size=32,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,  # matches <normalize>true</normalize> in Vespa
        )
        return embeddings

    def embed_single(self, text: str) -> list[float]:
        """Encode a single text to a Python list of floats."""
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
        model = SentenceTransformer(self._model_name, device=device)
        # Switch to fp16 for GPU to get ~3x throughput vs fp32.
        if device == "cuda":
            model.half()
            logger.info("Embedding model converted to fp16 for GPU inference.")
        logger.info("Embedding model %r ready on %s.", self._model_name, device)
        return model
