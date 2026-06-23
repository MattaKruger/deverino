"""HARNESS_FAKE_LLM forces the offline TestModel even when a key is configured."""

from __future__ import annotations

import pytest
from pydantic_ai.models.test import TestModel

from harness_poc.core.config import APISettings, LLMConfig
from harness_poc.core.runtime.pydantic_runtime import build_model

_KEYED = APISettings.model_construct(deepseek_api_key="sk-real")
_CFG = LLMConfig(provider="deepseek", model="deepseek-v4-flash", base_url=None)


def test_fake_llm_env_forces_testmodel(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARNESS_FAKE_LLM", "1")
    # A real key is present — the offline switch must still win.
    monkeypatch.setattr(APISettings, "load", classmethod(lambda _cls: _KEYED))
    assert isinstance(build_model(_CFG), TestModel)


def test_no_fake_llm_builds_real_model_when_keyed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HARNESS_FAKE_LLM", raising=False)
    monkeypatch.setattr(APISettings, "load", classmethod(lambda _cls: _KEYED))
    # Without the switch and with a key, it builds a real (non-Test) model.
    assert not isinstance(build_model(_CFG), TestModel)
