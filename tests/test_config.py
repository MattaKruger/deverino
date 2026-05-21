# tests/test_config.py
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from harness_poc.core.config import HarnessConfig, RetrievalConfig, TuiConfig


def _write_minimal_config(tmp_path: Path, extra: str = "") -> Path:
    cfg = tmp_path / "harness.yaml"
    base = textwrap.dedent("""
        version: 1
        llm:
          provider: deepseek
          model: deepseek-v4-flash
        paths:
          soul: harness_poc/system_prompts/SOUL.md
          system_tools: harness_poc/system_tools
          system_skills: harness_poc/system_skills
          project_skills: skills
          workflows: workflows
          pipelines: pipelines
          personas: personas
        runtime:
          database_url: postgresql://test:test@localhost/test
          default_container_image: python:3.14-slim
        observability:
          logfire: false
    """)
    cfg.write_text(base + extra, encoding="utf-8")
    return cfg


def test_retrieval_config_defaults_when_section_absent(tmp_path: Path) -> None:
    cfg = HarnessConfig.load(_write_minimal_config(tmp_path))
    r = cfg.retrieval
    assert r.enabled is True
    assert r.provider == "vespa"
    assert r.vespa_url == "http://localhost:8080"
    assert r.namespace == "deverino"
    assert r.schema == "doc_chunk"
    assert r.default_hits == 8
    assert r.default_mode == "hybrid"
    assert r.chunk_size_chars == 1800
    assert r.chunk_overlap_chars == 200
    assert r.max_feed_workers == 5
    assert r.query_timeout_seconds == 5
    assert r.auto_index_ignore_paths == []


def test_retrieval_config_parsed_from_yaml(tmp_path: Path) -> None:
    extra = textwrap.dedent("""
        retrieval:
          enabled: false
          vespa_url: http://vespa.internal:8080
          default_hits: 12
          chunk_size_chars: 2000
          auto_index_ignore_paths:
            - docs/generated
            - docs/acdl
    """)
    cfg = HarnessConfig.load(_write_minimal_config(tmp_path, extra))
    r = cfg.retrieval
    assert r.enabled is False
    assert r.vespa_url == "http://vespa.internal:8080"
    assert r.default_hits == 12
    assert r.chunk_size_chars == 2000
    assert r.auto_index_ignore_paths == ["docs/generated", "docs/acdl"]
    # unspecified fields keep defaults
    assert r.chunk_overlap_chars == 200


def test_retrieval_config_is_frozen() -> None:
    r = RetrievalConfig()
    with pytest.raises((AttributeError, TypeError)):
        r.enabled = False  # type: ignore[misc]


def test_tui_config_defaults_when_section_absent(tmp_path: Path) -> None:
    cfg = HarnessConfig.load(_write_minimal_config(tmp_path))
    assert cfg.tui.vim_enabled is False
    assert cfg.tui.vim_initial_mode == "insert"


def test_tui_config_parsed_from_yaml(tmp_path: Path) -> None:
    extra = textwrap.dedent("""
        tui:
          vim_enabled: true
          vim_initial_mode: normal
    """)
    cfg = HarnessConfig.load(_write_minimal_config(tmp_path, extra))
    assert cfg.tui.vim_enabled is True
    assert cfg.tui.vim_initial_mode == "normal"


def test_tui_config_rejects_invalid_initial_mode(tmp_path: Path) -> None:
    extra = textwrap.dedent("""
        tui:
          vim_initial_mode: visual
    """)
    with pytest.raises(ValueError, match="vim_initial_mode"):
        HarnessConfig.load(_write_minimal_config(tmp_path, extra))


def test_tui_config_is_frozen() -> None:
    t = TuiConfig()
    with pytest.raises((AttributeError, TypeError)):
        t.vim_enabled = True  # type: ignore[misc]
