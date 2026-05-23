from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from harness_poc.core.events import DocumentRetrieved, SearchFailed
from harness_poc.core.retrieval import SearchRequest
from harness_poc.core.skill_context import SkillResult
from harness_poc.core.vespa_client import LiveVespaDocumentClient

if TYPE_CHECKING:
    from harness_poc.core.retrieval import SearchResult
    from harness_poc.core.skill_context import SkillContext

_VALID_MODES = {"hybrid", "semantic", "keyword"}
_EXCERPT_CHARS = 300
_PREVIEW_EXCERPT_CHARS = 80
logger = logging.getLogger(__name__)


def _validate_arguments(
    arguments: dict[str, Any], ctx: SkillContext
) -> SkillResult | None:
    """Return an error SkillResult if arguments are invalid, or None if valid."""
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
        int(arguments.get("hits") or ctx.config.retrieval.default_hits)
    except (TypeError, ValueError):
        return SkillResult(
            status="failed",
            content="Invalid hits value. Provide a positive integer.",
            artifacts={},
        )

    return None


def execute(ctx: SkillContext, arguments: dict[str, Any]) -> SkillResult:
    error = _validate_arguments(arguments, ctx)
    if error is not None:
        return error

    query = str(arguments["query"]).strip()
    mode = str(arguments.get("mode") or ctx.config.retrieval.default_mode)
    hits = max(1, int(arguments.get("hits") or ctx.config.retrieval.default_hits))

    request = SearchRequest(
        query=query,
        mode=mode,
        hits=hits,
        source_id=_optional_str(arguments.get("source_id")),
        kind=_optional_str(arguments.get("kind")),
    )

    vespa = LiveVespaDocumentClient(ctx.config.retrieval)
    try:
        results = vespa.search(request)
    except Exception as exc:  # noqa: BLE001
        _append_search_failed_event(ctx, query, mode, exc)
        return SkillResult(
            status="failed",
            content=f"Search failed: {exc}. Is Vespa running? Run index_documents first.",
            artifacts={},
        )

    if not results:
        return SkillResult(
            status="success",
            content=(
                "No results found. If you haven't indexed documents yet, "
                "run index_documents first."
            ),
            artifacts={"query": query, "mode": mode, "results": []},
        )

    expand = arguments.get("expand")
    if expand is not None:
        selected = _parse_expand_indices(expand, len(results))
        if selected:
            _append_document_retrieved_event(
                ctx,
                query,
                mode,
                [results[index] for index in selected],
            )
        return _format_expand(results, selected, query, mode, ctx)

    _append_document_retrieved_event(ctx, query, mode, results)
    return _format_preview(results, query, mode)


def _parse_expand_indices(expand: object, max_results: int) -> list[int]:
    """Parse the *expand* argument into a sorted, deduplicated list of 0-based indices."""
    raw: list[object]
    if isinstance(expand, list):
        raw = list(expand)
    elif isinstance(expand, str):
        try:
            parsed = json.loads(expand)
        except (json.JSONDecodeError, ValueError):
            return []
        raw = list(parsed) if isinstance(parsed, list) else []
    else:
        return []

    indices: list[int] = []
    for item in raw:
        try:
            idx = int(str(item))
        except (TypeError, ValueError):
            continue
        zero_based = idx - 1  # 1-based → 0-based
        if 0 <= zero_based < max_results and zero_based not in indices:
            indices.append(zero_based)
    return sorted(indices)


def _format_preview(
    results: list[SearchResult],
    query: str,
    mode: str,
) -> SkillResult:
    """Return a compact preview so the user can choose which results to load."""
    plural = "s" if len(results) != 1 else ""
    lines: list[str] = [
        f'Found {len(results)} result{plural} for "{query}" (mode: {mode}):',
        "",
    ]
    for index, result in enumerate(results, 1):
        excerpt = result.text[:_PREVIEW_EXCERPT_CHARS].replace("\n", " ")
        if len(result.text) > _PREVIEW_EXCERPT_CHARS:
            excerpt += "..."
        lines.append(
            f'{index}. {result.uri} (score {result.relevance:.2f}) — "{excerpt}"'
        )

    lines.extend(
        [
            "",
            "Which results would you like me to load into context?",
            "Reply with numbers (e.g., 'load 1, 3') or 'load all'.",
        ]
    )

    artifacts = {
        "query": query,
        "mode": mode,
        "result_count": len(results),
        "results": [_result_artifact(result) for result in results],
    }

    return SkillResult(
        status="needs_orchestrator_action",
        content="\n".join(lines),
        artifacts=artifacts,
    )


def _format_expand(
    results: list[SearchResult],
    selected: list[int],
    query: str,
    mode: str,
    ctx: SkillContext,
) -> SkillResult:
    """Return full excerpts for the selected result indices only."""
    if not selected:
        return SkillResult(
            status="failed",
            content=(
                "No valid result indices provided for expand. "
                "Use numbers like 1, 2, 3 corresponding to the preview."
            ),
            artifacts={},
        )

    selected_results = [results[i] for i in selected]

    lines: list[str] = []
    for index, result in enumerate(selected_results, 1):
        excerpt = result.text[:_EXCERPT_CHARS] + (
            "..." if len(result.text) > _EXCERPT_CHARS else ""
        )
        lines.append(
            f"{index}. {result.uri}#chunk-{result.chunk_index} "
            f"(score {result.relevance:.2f})\n"
            f"   {excerpt}"
        )

    content = "\n\n".join(lines)
    max_chars = ctx.config.runtime.tool_result_max_chars
    if len(content) > max_chars:
        content = content[:max_chars] + "\n\n[truncated]"

    artifacts = {
        "query": query,
        "mode": mode,
        "results": [_result_artifact(result) for result in selected_results],
    }

    return SkillResult(status="success", content=content, artifacts=artifacts)


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


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


def _append_document_retrieved_event(
    ctx: SkillContext,
    query: str,
    mode: str,
    results: list[SearchResult],
) -> None:
    try:
        ctx.database.append_context_map_event(
            DocumentRetrieved(
                session_id=ctx.session_id,
                corpus_key=f"{ctx.config.project_id}:codebase",
                query=query,
                retrieved_doc_ids=[result.chunk_id for result in results],
                retrieved_doc_titles=[result.title for result in results],
                retrieval_strategy=mode,
            )
        )
    except (AttributeError, PermissionError):
        logger.debug("Skipping document_retrieved context-map event", exc_info=True)


def _append_search_failed_event(
    ctx: SkillContext,
    query: str,
    mode: str,
    exc: Exception,
) -> None:
    try:
        ctx.database.append_context_map_event(
            SearchFailed(
                session_id=ctx.session_id,
                corpus_key=f"{ctx.config.project_id}:codebase",
                attempted_query=query,
                strategy=mode,
                error=str(exc),
            )
        )
    except (AttributeError, PermissionError):
        logger.debug("Skipping search_failed context-map event", exc_info=True)
