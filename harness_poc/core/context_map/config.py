"""Config blocks for Distiller + deterministic Cartographer."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from harness_poc.core.config import LLMConfig

_DEFAULT_PRIORITY_WEIGHTS: dict[str, float] = {
    "dispute": 1.0,
    "schema": 0.9,
    "insight": 0.8,
    "boundary": 0.7,
    "entity": 0.6,
    "result": 0.5,
    "constant": 0.4,
}

_REQUIRED_WEIGHT_KEYS = frozenset(_DEFAULT_PRIORITY_WEIGHTS.keys())

_DISTILLER_KNOWN_KEYS = frozenset({"model", "max_retries", "prompt_template"})

_CARTOGRAPHER_KNOWN_KEYS = frozenset(
    {
        "token_budget",
        "tokenizer_name",
        "recency_bonus",
        "recency_cap",
        "staleness_penalty",
        "staleness_floor",
        "priority_weights",
        "prompt_block",
        "cross_corpus",
    }
)


@dataclass(frozen=True, slots=True)
class DistillerConfig:
    model: str | None = None  # None → fall back to HarnessConfig.llm
    max_retries: int = 3
    prompt_template: str = "distiller_v1"

    def resolved_model(self, llm_config: LLMConfig) -> str:
        """Return the effective model name, falling back to the primary LLM model."""
        return self.model or llm_config.model


@dataclass(frozen=True, slots=True)
class CartographerConfig:
    token_budget: int = 1024
    tokenizer_name: str = "cl100k_base"
    recency_bonus: float = 0.01
    recency_cap: float = 0.5
    staleness_penalty: float = 0.05
    staleness_floor: float = 0.2
    priority_weights: dict[str, float] = field(
        default_factory=lambda: dict(_DEFAULT_PRIORITY_WEIGHTS)
    )
    prompt_block: str = "structured"  # "structured" | "json" | "none"
    cross_corpus_enabled: bool = False
    cross_corpus_related_corpora: dict[str, list[str]] = field(default_factory=dict)
    cross_corpus_max_entries: int = 16
    cross_corpus_min_priority: float = 0.7


def load_distiller_config(raw: dict[str, Any]) -> DistillerConfig:
    unknown = set(raw) - _DISTILLER_KNOWN_KEYS
    if unknown:
        msg = f"unknown distiller config key(s): {sorted(unknown)}"
        raise ValueError(msg)
    return DistillerConfig(
        model=raw.get("model"),
        max_retries=int(raw.get("max_retries", 3)),
        prompt_template=str(raw.get("prompt_template", "distiller_v1")),
    )


def load_cartographer_config(raw: dict[str, Any]) -> CartographerConfig:
    unknown = set(raw) - _CARTOGRAPHER_KNOWN_KEYS
    if unknown:
        msg = f"unknown cartographer config key(s): {sorted(unknown)}"
        raise ValueError(msg)

    weights_raw = raw.get("priority_weights")
    if weights_raw is None:
        weights = dict(_DEFAULT_PRIORITY_WEIGHTS)
    else:
        if not isinstance(weights_raw, dict):
            msg = "cartographer.priority_weights must be a mapping"
            raise TypeError(msg)
        missing = _REQUIRED_WEIGHT_KEYS - set(weights_raw)
        if missing:
            msg = f"priority_weights missing key(s): {sorted(missing)}"
            raise ValueError(msg)
        weights = {k: float(weights_raw[k]) for k in _REQUIRED_WEIGHT_KEYS}

    return CartographerConfig(
        token_budget=int(raw.get("token_budget", 1024)),
        tokenizer_name=str(raw.get("tokenizer_name", "cl100k_base")),
        recency_bonus=float(raw.get("recency_bonus", 0.01)),
        recency_cap=float(raw.get("recency_cap", 0.5)),
        staleness_penalty=float(raw.get("staleness_penalty", 0.05)),
        staleness_floor=float(raw.get("staleness_floor", 0.2)),
        priority_weights=weights,
        prompt_block=str(raw.get("prompt_block", "structured")),
        cross_corpus_enabled=_parse_cross_corpus_bool(raw),
        cross_corpus_related_corpora=_parse_cross_corpus_corpora(raw),
        cross_corpus_max_entries=_parse_cross_corpus_int(raw, "max_cross_entries", 16),
        cross_corpus_min_priority=_parse_cross_corpus_float(raw, "min_priority", 0.7),
    )


def _parse_cross_corpus_bool(raw: dict[str, Any]) -> bool:
    cc = raw.get("cross_corpus")
    if isinstance(cc, dict):
        return bool(cc.get("enabled", False))
    return False


def _parse_cross_corpus_corpora(raw: dict[str, Any]) -> dict[str, list[str]]:
    cc = raw.get("cross_corpus")
    if isinstance(cc, dict):
        related_raw = cc.get("related_corpora")
        if isinstance(related_raw, dict):
            return {
                str(k): [str(vv) for vv in v] if isinstance(v, list) else []
                for k, v in related_raw.items()
            }
    return {}


def _parse_cross_corpus_int(raw: dict[str, Any], key: str, default: int) -> int:
    cc = raw.get("cross_corpus")
    if isinstance(cc, dict):
        return int(cc.get(key, default))
    return default


def _parse_cross_corpus_float(raw: dict[str, Any], key: str, default: float) -> float:
    cc = raw.get("cross_corpus")
    if isinstance(cc, dict):
        return float(cc.get(key, default))
    return default
