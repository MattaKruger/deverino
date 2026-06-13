"""Context Map Pipeline — Contract 2 of 4.

Transforms raw documents (corpus) into a typed, rendered DbContextMap that
ContextEngine injects into the prompt. Every stage in the pipeline (ingest
→ index → retrieve → assemble → render) must have a concrete implementation,
and the pipeline owner guarantees no stage is skipped.

Phase 1 implementation: harness_poc/v1/context_map.py (ContextMapV1)
"""

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# Render mode constants
# ---------------------------------------------------------------------------

RENDER_MODES = ("full", "summary", "diff")
DEFAULT_RENDER_MODE = "full"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class CorpusNotFoundError(FileNotFoundError):
    """No document corpus found at the expected path."""


class MaterializationError(RuntimeError):
    """Pipeline failed to materialize a DbContextMap from the corpus."""


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class DbContextMap:
    """The output of the full pipeline — ready for injection."""

    # Unique identifier for this context snapshot
    map_id: str

    # The rendered text that will be injected into the prompt
    rendered: str

    # Which render mode was used
    render_mode: str = DEFAULT_RENDER_MODE

    # Metadata: which documents contributed, how many tokens, etc.
    source_paths: list[str] = field(default_factory=list)
    token_count: int = 0

    # Pipeline provenance — which stages ran
    stages_run: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.map_id:
            msg = "DbContextMap.map_id must not be empty"
            raise ValueError(msg)


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class ContextMapMaterializer(Protocol):
    """Owns the full pipeline: ingest → index → retrieve → assemble → render.

    The materializer is responsible for calling the Renderer internally
    (stage 5). Callers receive a fully-rendered DbContextMap — they do
    not need to call a separate Renderer.
    """

    def materialize(self, corpus_path: str) -> DbContextMap:
        """Run the full pipeline and return a rendered context map.

        Args:
            corpus_path: Path to the document corpus root directory.

        Returns:
            A fully-rendered DbContextMap ready for prompt injection.

        Raises:
            CorpusNotFoundError: No corpus at corpus_path.
            MaterializationError: Pipeline failure in any stage.
        """
        ...
