from __future__ import annotations

from typing import TYPE_CHECKING, Any

from harness_poc.core.retrieval import SearchRequest
from harness_poc.core.skill_context import SkillResult
from harness_poc.core.vespa_client import LiveVespaDocumentClient

if TYPE_CHECKING:
    from harness_poc.core.retrieval import SearchResult
    from harness_poc.core.skill_context import SkillContext

_VALID_MODES = {"hybrid", "semantic", "keyword"}
_EXCERPT_CHARS = 300


def execute(ctx: SkillContext, arguments: dict[str, Any]) -> SkillResult:  # noqa: PLR0911
    if not ctx.config.retrieval.enabled:
        return SkillResult(
            status="failed",
            content="Retrieval is disabled. Set retrieval.enabled=true in harness.yaml.",
            artifacts={},
        )

    query = str(arguments.get("query") or "").strip()
    if not query:
        return SkillResult(
            status="failed",
            content="Empty query. Provide a non-empty search query.",
            artifacts={},
        )

    mode = str(arguments.get("mode") or ctx.config.retrieval.default_mode)
    if mode not in _VALID_MODES:
        return SkillResult(
            status="failed",
            content=f"Invalid mode {mode!r}. Choose from: hybrid, semantic, keyword.",
            artifacts={},
        )

    try:
        hits = int(arguments.get("hits") or ctx.config.retrieval.default_hits)
    except (TypeError, ValueError):
        return SkillResult(
            status="failed",
            content="Invalid hits value. Provide a positive integer.",
            artifacts={},
        )

    request = SearchRequest(
        query=query,
        mode=mode,
        hits=max(1, hits),
        source_id=_optional_str(arguments.get("source_id")),
        kind=_optional_str(arguments.get("kind")),
    )

    vespa = LiveVespaDocumentClient(ctx.config.retrieval)
    try:
        results = vespa.search(request)
    except Exception as exc:  # noqa: BLE001
        return SkillResult(
            status="failed",
            content=f"Search failed: {exc}. Is Vespa running? Run index_documents first.",
            artifacts={},
        )

    artifacts = {
        "query": query,
        "mode": mode,
        "results": [_result_artifact(result) for result in results],
    }

    if not results:
        return SkillResult(
            status="success",
            content=(
                "No results found. If you haven't indexed documents yet, run index_documents first."
            ),
            artifacts=artifacts,
        )

    content = _format_results(results)
    max_chars = ctx.config.runtime.tool_result_max_chars
    if len(content) > max_chars:
        content = content[:max_chars] + "\n\n[truncated]"

    return SkillResult(status="success", content=content, artifacts=artifacts)


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _format_results(results: list[SearchResult]) -> str:
    lines: list[str] = []
    for index, result in enumerate(results, 1):
        excerpt = result.text[:_EXCERPT_CHARS] + (
            "..." if len(result.text) > _EXCERPT_CHARS else ""
        )
        lines.append(
            f"{index}. {result.uri}#chunk-{result.chunk_index} (score {result.relevance:.2f})\n"
            f"   {excerpt}"
        )
    return "\n\n".join(lines)


def _result_artifact(result: SearchResult) -> dict[str, object]:
    return {
        "source_id": result.source_id,
        "title": result.title,
        "uri": result.uri,
        "chunk_id": result.chunk_id,
        "chunk_index": result.chunk_index,
        "relevance": result.relevance,
        "text": result.text,
        "kind": result.kind,
    }
