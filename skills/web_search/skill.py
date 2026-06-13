from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from harness_poc.core.skills import SkillResult

if TYPE_CHECKING:
    from harness_poc.core.skills import SkillContext

LANGSEARCH_API_BASE = "https://api.langsearch.com/v1/web-search"
MAX_RESULTS = 20
DEFAULT_COUNT = 5


def _find_dotenv_for_skill() -> Path | None:
    """Find .env walking up from cwd — replicated to avoid circular imports."""
    for directory in (Path.cwd(), *Path.cwd().parents):
        env_path = directory / ".env"
        if env_path.exists():
            return env_path
    return None


class LangSearchSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=None,
        env_file_encoding="utf-8",
        extra="ignore",
    )
    api_key: str | None = Field(
        default=None,
        validation_alias="LANGSEARCH_API_KEY",
    )

    @classmethod
    def load(cls) -> LangSearchSettings:
        env_path = _find_dotenv_for_skill()
        if env_path is None:
            return cls()
        return cls(_env_file=env_path)  # type: ignore[call-arg]  # ty: ignore[unknown-argument]


def execute(ctx: SkillContext, arguments: dict[str, Any]) -> SkillResult:  # noqa: PLR0911
    query = str(arguments.get("query") or "").strip()
    if not query:
        msg = "web_search requires a query string"
        raise ValueError(msg)
    if ctx.cancelled:
        return SkillResult(
            status="cancelled",
            content=f"cancelled: {ctx.cancellation.reason}",
            artifacts={"query": query, "reason": ctx.cancellation.reason},
        )

    count = _clamp_count(arguments.get("count", DEFAULT_COUNT))
    freshness = str(arguments.get("freshness", "noLimit"))
    summary = bool(arguments.get("summary", True))

    settings = LangSearchSettings.load()  # type: ignore[call-arg]

    if settings.api_key is None:
        return _mock_result(query, count)
    if ctx.cancelled:
        return SkillResult(
            status="cancelled",
            content=f"cancelled: {ctx.cancellation.reason}",
            artifacts={"query": query, "reason": ctx.cancellation.reason},
        )

    try:
        results = _search_langsearch(
            query, count, freshness, summary=summary, api_key=settings.api_key
        )
    except httpx.HTTPStatusError as exc:
        return SkillResult(
            status="failed",
            content=(
                f"LangSearch API returned HTTP {exc.response.status_code}: "
                f"{_truncate(exc.response.text, 200)}"
            ),
            artifacts={"query": query, "error": str(exc)},
        )
    except httpx.RequestError as exc:
        return SkillResult(
            status="failed",
            content=f"LangSearch API request failed: {exc}",
            artifacts={"query": query, "error": str(exc)},
        )

    if not results:
        return SkillResult(
            status="success",
            content=f"No results found for: {query}",
            artifacts={"query": query, "results": []},
        )

    formatted = _format_results(query, results)
    return SkillResult(
        status="success",
        content=formatted,
        artifacts={
            "query": query,
            "results": results,
            "count": len(results),
        },
    )


def _search_langsearch(
    query: str,
    count: int,
    freshness: str,
    *,
    summary: bool,
    api_key: str,
) -> list[dict[str, str]]:
    response = httpx.post(
        LANGSEARCH_API_BASE,
        json={
            "query": query,
            "freshness": freshness,
            "summary": summary,
            "count": count,
        },
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        timeout=30.0,
    )
    response.raise_for_status()
    body: dict[str, Any] = response.json()

    raw_results: list[dict[str, Any]] = body.get("data", {}).get("webPages", {}).get("value", [])
    return [
        {
            "title": str(r.get("name", "")),
            "url": str(r.get("url", "")),
            "description": str(r.get("snippet", "")),
        }
        for r in raw_results
    ]


def _format_results(query: str, results: list[dict[str, str]]) -> str:
    lines = [f"Web search results for: {query}\n"]
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. {r['title']}")
        lines.append(f"   {r['url']}")
        if r["description"]:
            lines.append(f"   {r['description']}")
        lines.append("")
    return "\n".join(lines).rstrip()


def _mock_result(query: str, count: int) -> SkillResult:
    return SkillResult(
        status="success",
        content=(
            f"[MOCK] Web search for: {query}\n"
            "Set LANGSEARCH_API_KEY to enable live search.\n\n"
            "This is a mock result — no API call was made."
        ),
        artifacts={
            "query": query,
            "results": [
                {
                    "title": f"Mock result {i} for: {query}",
                    "url": "https://example.com/mock-result",
                    "description": (
                        "This is a simulated search result. Configure "
                        "LANGSEARCH_API_KEY to get real results from LangSearch."
                    ),
                }
                for i in range(1, min(count, 3) + 1)
            ],
            "mock": True,
        },
    )


def _clamp_count(raw: object) -> int:
    try:
        count = int(str(raw))
    except (ValueError, TypeError):
        return DEFAULT_COUNT
    return max(1, min(count, MAX_RESULTS))


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else f"{text[:limit]}…"
