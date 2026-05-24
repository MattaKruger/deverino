from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from harness_poc.core.config import HarnessConfig
from harness_poc.core.context_map.config import (
    load_cartographer_config,
    load_distiller_config,
)


def test_distiller_config_defaults() -> None:
    cfg = load_distiller_config({})
    assert cfg.model is None
    assert cfg.max_retries == 3
    assert cfg.prompt_template == "distiller_v1"


def test_distiller_config_rejects_unknown_keys() -> None:
    with pytest.raises(ValueError, match="unknown distiller config key"):
        load_distiller_config({"banana": True})


def test_cartographer_config_defaults() -> None:
    cfg = load_cartographer_config({})
    assert cfg.token_budget == 1024
    assert cfg.tokenizer_name == "cl100k_base"
    # Per-type decay dicts (defaults)
    assert cfg.staleness_penalty["dispute"] == pytest.approx(0.02)
    assert cfg.staleness_penalty["constant"] == pytest.approx(0.01)
    assert cfg.staleness_floor["architecture"] == pytest.approx(0.60)
    assert cfg.recency_bonus["result"] == pytest.approx(0.00)
    assert cfg.recency_cap["architecture"] == pytest.approx(0.80)
    assert cfg.priority_weights["dispute"] == pytest.approx(1.0)
    assert cfg.priority_weights["constant"] == pytest.approx(0.4)
    assert cfg.priority_weights["architecture"] == pytest.approx(0.85)
    # Section budget share defaults
    assert cfg.section_budget_share["context_architecture"] == pytest.approx(0.25)
    assert cfg.section_budget_share["reusable_results"] == pytest.approx(0.05)


def test_cartographer_config_rejects_unknown_keys() -> None:
    with pytest.raises(ValueError, match="unknown cartographer config key"):
        load_cartographer_config({"mystery": 1})


def test_cartographer_config_requires_all_eight_weights() -> None:
    with pytest.raises(ValueError, match="priority_weights missing"):
        load_cartographer_config({"priority_weights": {"dispute": 1.0}})


def test_cartographer_config_rejects_old_scalar_decay() -> None:
    """Old global-scalar recency_bonus/cap/staleness should fail with clear error."""
    with pytest.raises(ValueError, match="deprecated global scalar"):
        load_cartographer_config({"recency_bonus": 0.05})


def test_harness_config_loads_cartographer_and_distiller(tmp_path: Path) -> None:
    config_path = tmp_path / "harness.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "llm": {"provider": "deepseek", "model": "deepseek-v4-flash"},
                "runtime": {
                    "database_url": "sqlite:///x.db",
                    "default_container_image": "python:3.14-slim",
                },
                "observability": {"logfire": False},
                "distiller": {"model": "anthropic/claude-haiku-4-5"},
                "cartographer": {"token_budget": 2048},
            }
        )
    )
    cfg = HarnessConfig.load(config_path)
    assert cfg.distiller.model == "anthropic/claude-haiku-4-5"
    assert cfg.cartographer.token_budget == 2048


_CROSS_CORPUS_YAML_QUOTED = """
cross_corpus:
  enabled: true
  related_corpora:
    "deverino:codebase":
      - "deverino:dashboard"
      - "deverino:benchmarks"
  max_cross_entries: 16
  min_priority: 0.7
"""


def test_cartographer_parses_cross_corpus_quoted_keys() -> None:
    raw = yaml.safe_load(_CROSS_CORPUS_YAML_QUOTED)
    cfg = load_cartographer_config(raw)
    assert cfg.cross_corpus_enabled is True
    assert cfg.cross_corpus_related_corpora == {
        "deverino:codebase": ["deverino:dashboard", "deverino:benchmarks"],
    }
    assert cfg.cross_corpus_max_entries == 16
    assert cfg.cross_corpus_min_priority == pytest.approx(0.7)


_CROSS_CORPUS_YAML_UNQUOTED = """
cross_corpus:
  enabled: true
  related_corpora:
    deverino:codebase:
      - deverino:dashboard
  max_cross_entries: 16
  min_priority: 0.7
"""


def test_cartographer_cross_corpus_unquoted_keys_also_work() -> None:
    """Unquoted colon-keys parse correctly with PyYAML 6.x in block style.

    The plan flagged a risk that `deverino:codebase` might be interpreted
    as a nested mapping. In practice, PyYAML handles this fine. Quoting is
    still recommended as a defensive measure for other YAML parsers.
    """
    raw = yaml.safe_load(_CROSS_CORPUS_YAML_UNQUOTED)
    cfg = load_cartographer_config(raw)
    assert cfg.cross_corpus_enabled is True
    assert cfg.cross_corpus_related_corpora == {
        "deverino:codebase": ["deverino:dashboard"],
    }
    assert cfg.cross_corpus_max_entries == 16
    assert cfg.cross_corpus_min_priority == pytest.approx(0.7)


def test_cartographer_cross_corpus_auto_discover_defaults_true() -> None:
    """cross_corpus_auto_discover defaults to True at config parse time."""
    cfg = load_cartographer_config({})
    assert cfg.cross_corpus_auto_discover is True


def test_cartographer_cross_corpus_auto_discover_false() -> None:
    cfg = load_cartographer_config({"cross_corpus_auto_discover": False})
    assert cfg.cross_corpus_auto_discover is False
