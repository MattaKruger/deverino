from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


@dataclass(frozen=True, slots=True)
class HarnessPaths:
    soul: Path
    system_skills: Path
    project_skills: Path
    workflows: Path
    pipelines: Path
    personas: Path


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    database_path: Path
    default_container_image: str


@dataclass(frozen=True, slots=True)
class ObservabilityConfig:
    logfire_enabled: bool


@dataclass(frozen=True, slots=True)
class LLMConfig:
    provider: str  # "deepseek" | "openai" | "anthropic"
    model: str
    base_url: (
        str | None
    )  # None unless overriding endpoint (openai-compatible only)


def _find_dotenv() -> Path | None:
    for directory in (Path.cwd(), *Path.cwd().parents):
        env_path = directory / ".env"
        if env_path.exists():
            return env_path
    return None


class APISettings(BaseSettings):
    """API keys loaded from .env via pydantic-settings, one per provider."""

    model_config = SettingsConfigDict(
        env_file=None,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    deepseek_api_key: str | None = Field(
        default=None, validation_alias="DEEPSEEK_API_KEY"
    )
    openai_api_key: str | None = Field(
        default=None, validation_alias="OPENAI_API_KEY"
    )
    anthropic_api_key: str | None = Field(
        default=None, validation_alias="ANTHROPIC_API_KEY"
    )

    @classmethod
    def load(cls) -> APISettings:
        env_path = _find_dotenv()
        if env_path is None:
            return cls()
        return cls(_env_file=env_path)  # type: ignore[call-arg]


@dataclass(frozen=True, slots=True)
class HarnessConfig:
    project_root: Path
    config_path: Path
    paths: HarnessPaths
    llm: LLMConfig
    runtime: RuntimeConfig
    observability: ObservabilityConfig

    @classmethod
    def load(cls, config_path: Path | None = None) -> HarnessConfig:
        resolved_config_path = config_path or find_harness_config()
        project_root = resolved_config_path.parent
        raw = yaml.safe_load(resolved_config_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            msg = f"Invalid harness config: {resolved_config_path}"
            raise TypeError(msg)

        paths_raw = _mapping(raw.get("paths"), "paths")
        runtime_raw = _mapping(raw.get("runtime"), "runtime")
        observability_raw = _mapping(raw.get("observability"), "observability")
        llm_raw = _mapping(raw.get("llm"), "llm")

        paths = HarnessPaths(
            soul=_resolve_path(
                project_root,
                paths_raw.get("soul", "harness_poc/system_prompts/SOUL.md"),
            ),
            system_skills=_resolve_path(
                project_root,
                paths_raw.get("system_skills", "harness_poc/system_skills"),
            ),
            project_skills=_resolve_path(
                project_root, paths_raw.get("project_skills", "skills")
            ),
            workflows=_resolve_path(
                project_root, paths_raw.get("workflows", "workflows")
            ),
            pipelines=_resolve_path(
                project_root, paths_raw.get("pipelines", "pipelines")
            ),
            personas=_resolve_path(
                project_root, paths_raw.get("personas", "personas")
            ),
        )
        runtime = RuntimeConfig(
            database_path=_resolve_path(
                project_root,
                runtime_raw.get("database_path", "harness_poc/blackboard.db"),
            ),
            default_container_image=str(
                runtime_raw.get("default_container_image", "python:3.12-slim")
            ),
        )
        observability = ObservabilityConfig(
            logfire_enabled=bool(observability_raw.get("logfire", False)),
        )
        llm = LLMConfig(
            provider=str(llm_raw.get("provider", "deepseek")),
            model=str(llm_raw.get("model", "deepseek-v4-flash")),
            base_url=llm_raw.get("base_url"),  # None is fine — defaults to None
        )

        return cls(
            project_root=project_root,
            config_path=resolved_config_path,
            paths=paths,
            llm=llm,
            runtime=runtime,
            observability=observability,
        )


def find_harness_config(start: Path | None = None) -> Path:
    search_start = (start or Path.cwd()).resolve()
    candidates = (search_start, *search_start.parents)

    for directory in candidates:
        config_path = directory / "harness.yaml"
        if config_path.exists():
            return config_path
    msg = f"Could not find harness.yaml from {search_start}"

    raise FileNotFoundError(msg)


def _mapping(value: object, name: str) -> dict[str, Any]:
    if value is None:
        return {}

    if not isinstance(value, dict):
        msg = f"harness.yaml section '{name}' must be a mapping"
        raise TypeError(msg)

    return cast("dict[str, Any]", value)


def _resolve_path(project_root: Path, value: object) -> Path:
    if not isinstance(value, str):
        msg = f"Expected path value to be a string, got {value!r}"
        raise TypeError(msg)
    path = Path(value)

    return path if path.is_absolute() else project_root / path
