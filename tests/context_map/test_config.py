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
    assert cfg.recency_bonus == pytest.approx(0.01)
    assert cfg.recency_cap == pytest.approx(0.5)
    assert cfg.staleness_penalty == pytest.approx(0.05)
    assert cfg.staleness_floor == pytest.approx(0.2)
    assert cfg.priority_weights["dispute"] == pytest.approx(1.0)
    assert cfg.priority_weights["constant"] == pytest.approx(0.4)


def test_cartographer_config_rejects_unknown_keys() -> None:
    with pytest.raises(ValueError, match="unknown cartographer config key"):
        load_cartographer_config({"mystery": 1})


def test_cartographer_config_requires_all_seven_weights() -> None:
    with pytest.raises(ValueError, match="priority_weights missing"):
        load_cartographer_config({"priority_weights": {"dispute": 1.0}})


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
