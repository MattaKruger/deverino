"""Unit tests for the count_tokens utility."""

from __future__ import annotations

from harness_poc.core.runtime import count_tokens


def test_count_tokens_basic() -> None:
    tokens = count_tokens([{"role": "user", "content": "hello"}])
    assert tokens > 0
    assert tokens < 20  # "hello" is just a few tokens


def test_count_tokens_scales_with_length() -> None:
    short = count_tokens([{"role": "user", "content": "hi"}])
    long = count_tokens([{"role": "user", "content": "hi " * 500}])
    assert long > short * 10
