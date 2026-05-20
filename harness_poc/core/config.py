from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


@dataclass(frozen=True, slots=True)
class HarnessPaths:
    soul: Path
    system_tools: Path
    system_skills: Path
    project_skills: Path
    workflows: Path
    pipelines: Path
    personas: Path


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    database_url: str
    default_container_image: str
    max_retries: int = 3
    max_tokens: int = 10_000
    container_ttl_seconds: int = 14_400
    max_harness_containers: int = 5
    chat_history_max_tokens: int = 24_000
    chat_history_recent_turns: int = 6
    tool_result_max_chars: int = 12_000
    materializer_poll_interval: float = 30.0
    materializer_max_event_tokens: int = 8000
    materializer_token_budget: int = 1024
    materializer_freeze_threshold: int = 3
    materializer_freeze_seconds: int = 300


@dataclass(frozen=True, slots=True)
class ObservabilityConfig:
    logfire_enabled: bool
    logfire_include_content: bool = False


@dataclass(frozen=True, slots=True)
class LLMConfig:
    provider: str  # "deepseek" | "openai" | "anthropic"
    model: str
    base_url: str | None  # None unless overriding endpoint (openai-compatible only)


@dataclass(frozen=True, slots=True)
class RetrievalConfig:
    enabled: bool = True
    provider: str = "vespa"
    vespa_url: str = "http://localhost:8080"
    namespace: str = "deverino"
    schema: str = "doc_chunk"
    default_hits: int = 8
    default_mode: str = "hybrid"
    chunk_size_chars: int = 1800
    chunk_overlap_chars: int = 200
    max_feed_workers: int = 5
    max_file_bytes: int = 5 * 1024 * 1024
    query_timeout_seconds: int = 5
    auto_index_paths: list[str] = field(default_factory=lambda: ["docs/"])


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

    deepseek_api_key: str | None = Field(default=None, validation_alias="DEEPSEEK_API_KEY")
    openai_api_key: str | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    anthropic_api_key: str | None = Field(default=None, validation_alias="ANTHROPIC_API_KEY")

    @classmethod
    def load(cls) -> APISettings:
        env_path = _find_dotenv()
        if env_path is None:
            return cls()
        return cls(_env_file=env_path)  # type: ignore[call-arg]  # ty: ignore[unknown-argument]


@dataclass(frozen=True, slots=True)
class HarnessConfig:
    project_root: Path
    config_path: Path
    paths: HarnessPaths
    llm: LLMConfig
    runtime: RuntimeConfig
    observability: ObservabilityConfig
    retrieval: RetrievalConfig = field(default_factory=RetrievalConfig)
    project_id: str = field(default="default")

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
            system_tools=_resolve_path(
                project_root,
                paths_raw.get("system_tools", "harness_poc/system_tools"),
            ),
            system_skills=_resolve_path(
                project_root,
                paths_raw.get("system_skills", "harness_poc/system_skills"),
            ),
            project_skills=_resolve_path(project_root, paths_raw.get("project_skills", "skills")),
            workflows=_resolve_path(project_root, paths_raw.get("workflows", "workflows")),
            pipelines=_resolve_path(project_root, paths_raw.get("pipelines", "pipelines")),
            personas=_resolve_path(project_root, paths_raw.get("personas", "personas")),
        )
        runtime = RuntimeConfig(
            database_url=str(
                runtime_raw.get("database_url", "sqlite:///harness_poc/blackboard.db")
            ),
            default_container_image=str(
                runtime_raw.get("default_container_image", "python:3.14-slim")
            ),
            max_retries=int(runtime_raw.get("max_retries", 3)),
            max_tokens=int(runtime_raw.get("max_tokens", 10_000)),
            container_ttl_seconds=int(runtime_raw.get("container_ttl_seconds", 14_400)),
            max_harness_containers=int(runtime_raw.get("max_harness_containers", 5)),
            chat_history_max_tokens=int(runtime_raw.get("chat_history_max_tokens", 24_000)),
            chat_history_recent_turns=int(runtime_raw.get("chat_history_recent_turns", 6)),
            tool_result_max_chars=int(runtime_raw.get("tool_result_max_chars", 12_000)),
            materializer_poll_interval=float(runtime_raw.get("materializer_poll_interval", 30.0)),
            materializer_max_event_tokens=int(
                runtime_raw.get("materializer_max_event_tokens", 8000)
            ),
            materializer_token_budget=int(runtime_raw.get("materializer_token_budget", 1024)),
            materializer_freeze_threshold=int(
                runtime_raw.get("materializer_freeze_threshold", 3)
            ),
            materializer_freeze_seconds=int(runtime_raw.get("materializer_freeze_seconds", 300)),
        )
        observability = ObservabilityConfig(
            logfire_enabled=bool(observability_raw.get("logfire", False)),
            logfire_include_content=bool(observability_raw.get("logfire_include_content", False)),
        )
        llm = LLMConfig(
            provider=str(llm_raw.get("provider", "deepseek")),
            model=str(llm_raw.get("model", "deepseek-v4-flash")),
            base_url=llm_raw.get("base_url"),  # None is fine — defaults to None
        )

        retrieval_raw = _mapping(raw.get("retrieval"), "retrieval")
        retrieval = RetrievalConfig(
            enabled=bool(retrieval_raw.get("enabled", True)),
            provider=str(retrieval_raw.get("provider", "vespa")),
            vespa_url=str(retrieval_raw.get("vespa_url", "http://localhost:8080")),
            namespace=str(retrieval_raw.get("namespace", "deverino")),
            schema=str(retrieval_raw.get("schema", "doc_chunk")),
            default_hits=int(retrieval_raw.get("default_hits", 8)),
            default_mode=str(retrieval_raw.get("default_mode", "hybrid")),
            chunk_size_chars=int(retrieval_raw.get("chunk_size_chars", 1800)),
            chunk_overlap_chars=int(retrieval_raw.get("chunk_overlap_chars", 200)),
            max_feed_workers=int(retrieval_raw.get("max_feed_workers", 5)),
            max_file_bytes=int(retrieval_raw.get("max_file_bytes", 5 * 1024 * 1024)),
            query_timeout_seconds=int(retrieval_raw.get("query_timeout_seconds", 5)),
            auto_index_paths=_parse_string_list(
                retrieval_raw.get("auto_index_paths", ["docs/"])
            ),
        )

        project_raw = _mapping(raw.get("project"), "project")
        project_id = str(project_raw.get("id") or "")
        if not project_id:
            project_id = hashlib.md5(
                str(project_root).encode(),
                usedforsecurity=False,
            ).hexdigest()[:8]

        return cls(
            project_root=project_root,
            config_path=resolved_config_path,
            paths=paths,
            llm=llm,
            runtime=runtime,
            observability=observability,
            retrieval=retrieval,
            project_id=project_id,
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


def _parse_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        msg = f"Expected a list of strings, got {type(value).__name__}"
        raise TypeError(msg)
    result: list[str] = []
    for item in value:
        if isinstance(item, str):
            result.append(item)
        else:
            result.append(str(item))
    return result


def _resolve_path(project_root: Path, value: object) -> Path:
    if not isinstance(value, str):
        msg = f"Expected path value to be a string, got {value!r}"
        raise TypeError(msg)
    path = Path(value)

    return path if path.is_absolute() else project_root / path
