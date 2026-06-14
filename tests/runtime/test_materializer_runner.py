from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import MagicMock

from sqlalchemy import Engine

from harness_poc.core.events.context_map_events import ContextualInsightDiscovered
from harness_poc.core.execution import MaterializerRunner
from harness_poc.core.storage.database import BlackboardDatabase

if TYPE_CHECKING:
    from harness_poc.app_factory import Runtime
    from harness_poc.core.config import HarnessConfig
    from harness_poc.core.skills import SkillRunner


# ---------------------------------------------------------------------------
# Existing test
# ---------------------------------------------------------------------------


class _FakeSkillRunner:
    pass


def test_materializer_swap_runtime_preserves_no_change_count() -> None:
    db = cast("BlackboardDatabase", MagicMock())
    config = cast("HarnessConfig", SimpleNamespace())
    initial_skill_runner = cast("SkillRunner", _FakeSkillRunner())
    replacement_skill_runner = cast("SkillRunner", _FakeSkillRunner())
    replacement_config = cast("HarnessConfig", SimpleNamespace())
    runner = MaterializerRunner(
        db,
        initial_skill_runner,
        config,
        session_id="s1",
    )
    runner._no_change_count["deverino:codebase"] = 5

    replacement_runtime = cast(
        "Runtime",
        SimpleNamespace(skill_runner=replacement_skill_runner, config=replacement_config),
    )
    runner.swap_runtime(replacement_runtime)

    assert runner._no_change_count["deverino:codebase"] == 5
    assert runner._skill_runner is replacement_skill_runner
    assert runner._config is replacement_config


# ---------------------------------------------------------------------------
# Poll loop tests
# ---------------------------------------------------------------------------


@dataclass
class _FakeSkillResult:
    status: str = "success"
    content: str = ""
    artifacts: dict[str, Any] = field(default_factory=dict)


class _ControlledSkillRunner:
    """Skill runner that returns pre-configured results."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self._results: dict[str, _FakeSkillResult] = {}

    def set_result(self, skill_name: str, result: _FakeSkillResult) -> None:
        self._results[skill_name] = result

    def execute_skill(
        self, skill_name: str, arguments: dict, session_id: str, **kwargs: Any
    ) -> _FakeSkillResult:
        self.calls.append(
            {"skill_name": skill_name, "arguments": arguments, "session_id": session_id}
        )
        result = self._results.get(skill_name)
        if result is not None:
            return result
        return _FakeSkillResult(
            status="success",
            artifacts={"map_changed": True, "token_count": 0},
        )


class TestMaterializerPollLoop:
    """Exercises MaterializerRunner._poll_once with real DB and mock skill runner."""

    def test_poll_once_processes_pending_keys(self, db_engine: Engine) -> None:
        db = BlackboardDatabase(db_engine)
        skill_runner = _ControlledSkillRunner()

        db.append_context_map_event(
            ContextualInsightDiscovered(
                session_id="test-poll",
                corpus_key="deverino:codebase",
                insight="Test insight for poll loop.",
                supporting_events=[],
                map_section="context_understanding",
            )
        )
        assert "deverino:codebase" in db.get_pending_corpus_keys()

        runner = MaterializerRunner(
            db,
            skill_runner,
            MagicMock(),
            session_id="test-poll",  # type: ignore[arg-type]
        )

        asyncio.run(runner._poll_once())

        assert len(skill_runner.calls) == 1
        assert skill_runner.calls[0]["skill_name"] == "context-map-materializer"
        assert skill_runner.calls[0]["arguments"]["corpus_key"] == "deverino:codebase"

    def test_poll_once_respects_freeze(self, db_engine: Engine) -> None:
        db = BlackboardDatabase(db_engine)
        skill_runner = _ControlledSkillRunner()

        db.append_context_map_event(
            ContextualInsightDiscovered(
                session_id="test-freeze",
                corpus_key="deverino:codebase",
                insight="Test insight behind freeze.",
                supporting_events=[],
                map_section="context_understanding",
            )
        )
        assert "deverino:codebase" in db.get_pending_corpus_keys()

        # Override is_map_frozen to simulate frozen map
        original = db.is_map_frozen
        db.is_map_frozen = lambda _ck, _now=None: True  # type: ignore[method-assign]
        try:
            runner = MaterializerRunner(
                db,
                skill_runner,
                MagicMock(),
                session_id="test-freeze",  # type: ignore[arg-type]
            )
            asyncio.run(runner._poll_once())
            assert len(skill_runner.calls) == 0
        finally:
            db.is_map_frozen = original  # type: ignore[method-assign]

    def test_poll_once_handles_skill_failure(self, db_engine: Engine) -> None:
        db = BlackboardDatabase(db_engine)
        skill_runner = _ControlledSkillRunner()
        skill_runner.set_result(
            "context-map-materializer",
            _FakeSkillResult(status="failed", content="LLM unavailable"),
        )

        db.append_context_map_event(
            ContextualInsightDiscovered(
                session_id="test-fail",
                corpus_key="deverino:codebase",
                insight="Test insight for failure path.",
                supporting_events=[],
                map_section="context_understanding",
            )
        )

        runner = MaterializerRunner(
            db,
            skill_runner,
            MagicMock(),
            session_id="test-fail",  # type: ignore[arg-type]
        )

        asyncio.run(runner._poll_once())

        assert len(skill_runner.calls) == 1
