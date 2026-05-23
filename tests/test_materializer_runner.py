from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, cast
from unittest.mock import MagicMock

from harness_poc.core.materializer_runner import MaterializerRunner

if TYPE_CHECKING:
    from harness_poc.app_factory import Runtime
    from harness_poc.core.config import HarnessConfig
    from harness_poc.core.skill_runner import SkillRunner
    from harness_poc.core.storage import BlackboardDatabase


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
