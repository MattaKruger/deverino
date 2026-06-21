"""Deterministic Cartographer + Distiller package.

See docs/superpowers/specs/2026-05-23-deterministic-cartographer-design.md.
"""

from harness_poc.core.context_map.cartographer import deterministic_cartographer
from harness_poc.core.context_map.config import (
    CartographerConfig,
    DistillerConfig,
    load_cartographer_config,
    load_distiller_config,
)
from harness_poc.core.context_map.copt_gate import embed_single, embed_summaries
from harness_poc.core.context_map.distiller import run_distiller
from harness_poc.core.context_map.format import (
    format_context_window,
    format_persona_lens,
    format_verified_state,
    format_working_context,
)
from harness_poc.core.context_map.render import render_context_map
from harness_poc.core.context_map.schema import (
    CartographerResult,
    DistilledBatch,
    DistillerEntry,
    EvictionRecord,
    MapEntry,
    ObservationType,
    Tag,
)
from harness_poc.core.context_map.sections import SECTION_MAP, assign_section

__all__ = [
    "SECTION_MAP",
    "CartographerConfig",
    "CartographerResult",
    "DistilledBatch",
    "DistillerConfig",
    "DistillerEntry",
    "EvictionRecord",
    "MapEntry",
    "ObservationType",
    "Tag",
    "assign_section",
    "deterministic_cartographer",
    "embed_single",
    "embed_summaries",
    "format_context_window",
    "format_persona_lens",
    "format_verified_state",
    "format_working_context",
    "load_cartographer_config",
    "load_distiller_config",
    "render_context_map",
    "run_distiller",
]
