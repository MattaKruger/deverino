"""Config blocks for Distiller + deterministic Cartographer."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

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
    }
)


@dataclass(frozen=True, slots=True)
class DistillerConfig:
    model: str | None = None  # None → fall back to HarnessConfig.llm
    max_retries: int = 3
    prompt_template: str = "distiller_v1"


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
    )
