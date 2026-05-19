from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, cast

from harness_poc.core.config import (
    HarnessConfig,
    HarnessPaths,
    LLMConfig,
    ObservabilityConfig,
    RuntimeConfig,
)
from harness_poc.core.database import BlackboardDatabase
from harness_poc.core.skill_runner import SkillRunner
from harness_poc.repl import _parse_skill_arguments, is_skill_name

if TYPE_CHECKING:
    from harness_poc.app_factory import AppState


def test_single_positional_skill_argument_maps_to_primary_parameter(
    tmp_path: Path,
) -> None:
    app_state = _fake_app_state(tmp_path)

    arguments = _parse_skill_arguments(
        app_state,
        "summarize_memory",
        '"research_reflection"',
    )

    assert arguments == {"memory_key": "research_reflection"}


def test_known_skill_name_is_discovered(tmp_path: Path) -> None:
    app_state = _fake_app_state(tmp_path)

    assert is_skill_name(app_state, "summarize_memory")


def _fake_app_state(tmp_path: Path) -> AppState:
    config = _test_config(tmp_path)
    database = BlackboardDatabase(config.runtime.database_path)
    database.create_tables()
    return cast(
        "AppState",
        _FakeAppState(
            skill_runner=SkillRunner(database=database, config=config),
            config=config,
        ),
    )


class _FakeAppState:
    def __init__(self, *, skill_runner: SkillRunner, config: HarnessConfig) -> None:
        self.skill_runner = skill_runner
        self.config = config


def _test_config(tmp_path: Path) -> HarnessConfig:
    project_root = Path.cwd()
    return HarnessConfig(
        project_root=project_root,
        config_path=project_root / "harness.yaml",
        paths=HarnessPaths(
            soul=project_root / "harness_poc/system_prompts/SOUL.md",
            system_skills=project_root / "harness_poc/system_skills",
            project_skills=project_root / "skills",
            workflows=project_root / "workflows",
            pipelines=project_root / "pipelines",
            personas=project_root / "personas",
        ),
        runtime=RuntimeConfig(
            database_path=tmp_path / "blackboard.db",
            default_container_image="python:3.12-slim",
        ),
        observability=ObservabilityConfig(logfire_enabled=False),
        llm=LLMConfig(provider="deepseek", model="deepseek-v4-flash", base_url=None),
    )
