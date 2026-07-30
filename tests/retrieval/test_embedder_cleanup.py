"""Tests for embedder.py docstring/model consistency after cleanup."""

from __future__ import annotations


def test_default_model_is_snowflake() -> None:
    from harness_poc.core.retrieval.embedder import DEFAULT_MODEL

    assert DEFAULT_MODEL == "Snowflake/snowflake-arctic-embed-l-v2.0"


def test_embed_query_does_not_use_lora_adapter() -> None:
    """embed_query should not pass prompt_name='retrieval.query' — Snowflake has no LoRA."""
    import inspect

    from harness_poc.core.retrieval.embedder import TextEmbedder

    source = inspect.getsource(TextEmbedder.embed_query)
    assert "retrieval.query" not in source
