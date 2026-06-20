"""Config blocks for Distiller + deterministic Cartographer."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from harness_poc.core.context_map.sections import SECTION_MAP

if TYPE_CHECKING:
    from harness_poc.core.config import LLMConfig

_DEFAULT_PRIORITY_WEIGHTS: dict[str, float] = {
    "dispute": 1.0,
    "schema": 0.9,
    "architecture": 0.85,
    "insight": 0.8,
    "boundary": 0.7,
    "entity": 0.6,
    "result": 0.5,
    "constant": 0.4,
}

_REQUIRED_WEIGHT_KEYS = frozenset(_DEFAULT_PRIORITY_WEIGHTS.keys())

# Scored observation types (all types except "obsolete", which never enters scoring).
_SCORED_TYPES = frozenset(_REQUIRED_WEIGHT_KEYS)

_DEFAULT_STALENESS_PENALTY: dict[str, float] = {
    "dispute": 0.02,
    "schema": 0.03,
    "insight": 0.05,
    "architecture": 0.01,
    "boundary": 0.02,
    "entity": 0.05,
    "result": 0.10,
    "constant": 0.01,
}

_DEFAULT_STALENESS_FLOOR: dict[str, float] = {
    "dispute": 0.50,
    "schema": 0.40,
    "insight": 0.20,
    "architecture": 0.60,
    "boundary": 0.30,
    "entity": 0.20,
    "result": 0.05,
    "constant": 0.60,
}

_DEFAULT_RECENCY_BONUS: dict[str, float] = {
    "dispute": 0.01,
    "schema": 0.01,
    "insight": 0.01,
    "architecture": 0.01,
    "boundary": 0.01,
    "entity": 0.01,
    "result": 0.00,
    "constant": 0.01,
}

_DEFAULT_RECENCY_CAP: dict[str, float] = {
    "dispute": 0.50,
    "schema": 0.50,
    "insight": 0.40,
    "architecture": 0.80,
    "boundary": 0.30,
    "entity": 0.50,
    "result": 0.10,
    "constant": 0.30,
}

_DEFAULT_SECTION_BUDGET_SHARE: dict[str, float] = {
    "context_architecture": 0.25,
    "parsing_schema": 0.20,
    "context_understanding": 0.25,
    "context_roadmap": 0.15,
    "domain_constants": 0.10,
    "reusable_results": 0.05,
}

_SECTION_BUDGET_SHARE_TOLERANCE = 0.001

_DISTILLER_KNOWN_KEYS = frozenset({"model", "max_retries", "prompt_template", "timeout_seconds"})

_OLD_SCALAR_KEYS = frozenset(
    {"recency_bonus", "recency_cap", "staleness_penalty", "staleness_floor"}
)

_CARTOGRAPHER_KNOWN_KEYS = frozenset(
    {
        "token_budget",
        "tokenizer_name",
        "staleness_penalty",
        "staleness_floor",
        "recency_bonus",
        "recency_cap",
        "priority_weights",
        "section_budget_share",
        "prompt_block",
        "cross_corpus",
        "cross_corpus_auto_discover",
    }
)


@dataclass(frozen=True, slots=True)
class DistillerConfig:
    model: str | None = None  # None → fall back to HarnessConfig.llm
    max_retries: int = 3
    prompt_template: str = "distiller_v1"
    timeout_seconds: float = 120.0  # per-attempt timeout for the LLM call

    def resolved_model(self, llm_config: LLMConfig) -> str:
        """Return the effective model name, falling back to the primary LLM model."""
        return self.model or llm_config.model


@dataclass(frozen=True, slots=True)
class CartographerConfig:
    token_budget: int = 1024
    tokenizer_name: str = "cl100k_base"

    # --- Per-type decay (replaces global scalars) ---
    staleness_penalty: dict[str, float] = field(
        default_factory=lambda: dict(_DEFAULT_STALENESS_PENALTY)
    )
    staleness_floor: dict[str, float] = field(
        default_factory=lambda: dict(_DEFAULT_STALENESS_FLOOR)
    )
    recency_bonus: dict[str, float] = field(default_factory=lambda: dict(_DEFAULT_RECENCY_BONUS))
    recency_cap: dict[str, float] = field(default_factory=lambda: dict(_DEFAULT_RECENCY_CAP))

    priority_weights: dict[str, float] = field(
        default_factory=lambda: dict(_DEFAULT_PRIORITY_WEIGHTS)
    )
    section_budget_share: dict[str, float] = field(
        default_factory=lambda: dict(_DEFAULT_SECTION_BUDGET_SHARE)
    )

    prompt_block: str = "structured"  # "structured" | "json" | "none"
    cross_corpus_enabled: bool = False
    cross_corpus_related_corpora: dict[str, list[str]] = field(default_factory=dict)
    cross_corpus_max_entries: int = 16
    cross_corpus_min_priority: float = 0.7
    cross_corpus_auto_discover: bool = True


def load_distiller_config(raw: dict[str, Any]) -> DistillerConfig:
    unknown = set(raw) - _DISTILLER_KNOWN_KEYS
    if unknown:
        msg = f"unknown distiller config key(s): {sorted(unknown)}"
        raise ValueError(msg)
    return DistillerConfig(
        model=raw.get("model"),
        max_retries=int(raw.get("max_retries", 3)),
        prompt_template=str(raw.get("prompt_template", "distiller_v1")),
        timeout_seconds=float(raw.get("timeout_seconds", 120.0)),
    )


def load_cartographer_config(raw: dict[str, Any]) -> CartographerConfig:
    unknown = set(raw) - _CARTOGRAPHER_KNOWN_KEYS
    if unknown:
        msg = f"unknown cartographer config key(s): {sorted(unknown)}"
        raise ValueError(msg)

    # Reject old global-scalar values for keys that are now per-type dicts.
    old_scalars_found: list[str] = []
    for old_key in _OLD_SCALAR_KEYS:
        val = raw.get(old_key)
        if val is not None and not isinstance(val, dict):
            old_scalars_found.append(old_key)
    if old_scalars_found:
        msg = (
            f"cartographer config uses deprecated global scalar(s): {sorted(old_scalars_found)}. "
            "Use per-type decay dictionaries instead — each of staleness_penalty, "
            "staleness_floor, recency_bonus, and recency_cap must be a mapping keyed "
            "by observation_type. See harness.yaml §6 for the complete format."
        )
        raise ValueError(msg)

    # -- priority_weights --
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
        extra_keys = set(weights_raw) - _REQUIRED_WEIGHT_KEYS
        if extra_keys:
            msg = f"priority_weights has unknown key(s): {sorted(extra_keys)}"
            raise ValueError(msg)
        weights = {k: float(weights_raw[k]) for k in _REQUIRED_WEIGHT_KEYS}

    # -- per-type decay dicts --
    staleness_penalty = _parse_per_type_dict(raw, "staleness_penalty", _DEFAULT_STALENESS_PENALTY)
    staleness_floor = _parse_per_type_dict(raw, "staleness_floor", _DEFAULT_STALENESS_FLOOR)
    recency_bonus = _parse_per_type_dict(raw, "recency_bonus", _DEFAULT_RECENCY_BONUS)
    recency_cap = _parse_per_type_dict(raw, "recency_cap", _DEFAULT_RECENCY_CAP)

    # -- section_budget_share --
    section_budget_share = _parse_section_budget_share(raw)

    # -- cross_corpus --
    cc = raw.get("cross_corpus")
    cc_dict = cc if isinstance(cc, dict) else {}

    return CartographerConfig(
        token_budget=int(raw.get("token_budget", 1024)),
        tokenizer_name=str(raw.get("tokenizer_name", "cl100k_base")),
        staleness_penalty=staleness_penalty,
        staleness_floor=staleness_floor,
        recency_bonus=recency_bonus,
        recency_cap=recency_cap,
        priority_weights=weights,
        section_budget_share=section_budget_share,
        prompt_block=str(raw.get("prompt_block", "structured")),
        cross_corpus_enabled=bool(cc_dict.get("enabled", False)),
        cross_corpus_related_corpora=_parse_cross_corpus_corpora(cc_dict),
        cross_corpus_max_entries=int(cc_dict.get("max_cross_entries", 16)),
        cross_corpus_min_priority=float(cc_dict.get("min_priority", 0.7)),
        cross_corpus_auto_discover=bool(raw.get("cross_corpus_auto_discover", True)),
    )


def _parse_cross_corpus_corpora(cc: dict[str, Any]) -> dict[str, list[str]]:
    related_raw = cc.get("related_corpora")
    if isinstance(related_raw, dict):
        return {
            str(k): [str(vv) for vv in v] if isinstance(v, list) else []
            for k, v in related_raw.items()
        }
    return {}


def _parse_per_type_dict(
    raw: dict[str, Any],
    key: str,
    defaults: dict[str, float],
) -> dict[str, float]:
    """Parse a per-type decay dictionary from raw config.

    Falls back to defaults when absent. Validates that all scored types are
    present — missing keys are a hard error. Unknown keys are rejected.
    """
    value = raw.get(key)
    if value is None:
        return dict(defaults)
    if not isinstance(value, dict):
        msg = f"cartographer.{key} must be a mapping keyed by observation_type"
        raise TypeError(msg)
    missing = _SCORED_TYPES - set(value)
    if missing:
        msg = f"{key} missing key(s): {sorted(missing)}"
        raise ValueError(msg)
    extra = set(value) - _SCORED_TYPES
    if extra:
        msg = f"{key} has unknown key(s): {sorted(extra)}"
        raise ValueError(msg)
    return {k: float(value[k]) for k in _SCORED_TYPES}


def _parse_section_budget_share(raw: dict[str, Any]) -> dict[str, float]:
    """Parse section_budget_share from raw config with bidirectional validation.

    Every key must be a known section name (value in SECTION_MAP). Every
    section name must have an entry. Values must sum to 1.0 ± 0.001.
    """
    value = raw.get("section_budget_share")
    if value is None:
        return dict(_DEFAULT_SECTION_BUDGET_SHARE)
    if not isinstance(value, dict):
        msg = "cartographer.section_budget_share must be a mapping"
        raise TypeError(msg)

    known_sections = set(SECTION_MAP.values())
    raw_sections = {str(k): float(v) for k, v in value.items()}

    unknown_sections = set(raw_sections) - known_sections
    if unknown_sections:
        msg = f"section_budget_share has unknown section(s): {sorted(unknown_sections)}"
        raise ValueError(msg)

    missing_sections = known_sections - set(raw_sections)
    if missing_sections:
        msg = f"section_budget_share missing section(s): {sorted(missing_sections)}"
        raise ValueError(msg)

    total = sum(raw_sections.values())
    if abs(total - 1.0) > _SECTION_BUDGET_SHARE_TOLERANCE:
        msg = f"section_budget_share shares sum to {total:.3f}, must sum to 1.0"
        raise ValueError(msg)

    return {k: raw_sections[k] for k in known_sections}
