from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

    from harness_poc.core.config import RetrievalConfig
    from harness_poc.core.retrieval import DocumentChunk

from harness_poc.core.retrieval import (
    FeedSummary,
    SearchRequest,
    SearchResult,
)

HTTP_OK = 200
HTTP_CREATED = 201
DELETE_BATCH_SIZE = 400


class LiveVespaDocumentClient:
    """Thin pyvespa adapter implementing the VespaDocumentClient protocol."""

    def __init__(self, config: RetrievalConfig) -> None:
        self._url = config.vespa_url
        self._namespace = config.namespace
        self._schema = config.schema
        self._max_workers = config.max_feed_workers
        self._timeout = config.query_timeout_seconds

    def health_check(self) -> None:
        from vespa.application import Vespa  # noqa: PLC0415

        app = Vespa(url=self._url)
        response = app.get_application_status()
        status_code = response.status_code if response is not None else None
        if status_code != HTTP_OK:
            msg = f"Vespa health check failed: HTTP {status_code}"
            raise RuntimeError(msg)

    def feed_chunks(self, chunks: Iterable[DocumentChunk]) -> FeedSummary:
        from vespa.application import Vespa  # noqa: PLC0415

        app = Vespa(url=self._url)
        fed = 0
        failed = 0
        failed_ids: list[str] = []
        with app.syncio(connections=self._max_workers) as session:
            for chunk in chunks:
                fields = {
                    "source_id": chunk.source_id,
                    "uri": chunk.uri,
                    "title": chunk.title,
                    "chunk_id": chunk.chunk_id,
                    "chunk_index": chunk.chunk_index,
                    "text": chunk.text,
                    "kind": chunk.kind,
                    "content_hash": chunk.content_hash,
                    "updated_at": chunk.updated_at,
                }
                response = session.feed_data_point(
                    schema=self._schema,
                    data_id=chunk.chunk_id,
                    fields=fields,
                    namespace=self._namespace,
                )
                if response.status_code in (HTTP_OK, HTTP_CREATED):
                    fed += 1
                else:
                    failed += 1
                    failed_ids.append(chunk.chunk_id)
        return FeedSummary(fed=fed, failed=failed, failed_ids=failed_ids)

    def delete_source(self, source_id: str) -> None:
        from vespa.application import Vespa  # noqa: PLC0415

        app = Vespa(url=self._url)
        with app.syncio() as session:
            while True:
                result = session.query(
                    body={
                        "yql": (
                            f"select chunk_id from {self._schema} where "  # noqa: S608
                            "source_id contains @source_id"
                        ),
                        "source_id": source_id,
                        "hits": DELETE_BATCH_SIZE,
                        "timeout": str(self._timeout),
                    }
                )
                if not result.hits:
                    break

                for hit in result.hits:
                    chunk_id = hit["fields"]["chunk_id"]
                    session.delete_data(
                        schema=self._schema,
                        data_id=chunk_id,
                        namespace=self._namespace,
                    )

    def search(self, request: SearchRequest) -> list[SearchResult]:
        from vespa.application import Vespa  # noqa: PLC0415

        body = _build_query_body(request, schema=self._schema, timeout=self._timeout)
        app = Vespa(url=self._url)
        with app.syncio() as session:
            result = session.query(body=body)
        return [_normalize_hit(hit) for hit in result.hits]


def _build_query_body(request: SearchRequest, schema: str, timeout: int) -> dict:
    filter_clauses: list[str] = []
    extra_params: dict = {}

    if request.source_id:
        filter_clauses.append("source_id contains @filter_source_id")
        extra_params["filter_source_id"] = request.source_id
    if request.kind:
        filter_clauses.append("kind contains @filter_kind")
        extra_params["filter_kind"] = request.kind

    filter_str = (" and " + " and ".join(filter_clauses)) if filter_clauses else ""

    if request.mode == "keyword":
        where = f"default contains ({{targetHits:100}}text(@query)){filter_str}"
        body: dict = {
            "yql": f"select * from {schema} where {where}",  # noqa: S608
            "query": request.query,
            "ranking.profile": "keyword",
            "hits": request.hits,
            "timeout": str(timeout),
        }
    elif request.mode == "semantic":
        where = f"({{targetHits:20}}nearestNeighbor(embedding,q)){filter_str}"
        body = {
            "yql": f"select * from {schema} where {where}",  # noqa: S608
            "query": request.query,
            "input.query(q)": "embed(@query)",
            "ranking.profile": "semantic",
            "hits": request.hits,
            "timeout": str(timeout),
        }
    else:
        where = (
            f"(default contains ({{targetHits:100}}text(@query))"
            f" or ({{targetHits:20}}nearestNeighbor(embedding,q))){filter_str}"
        )
        body = {
            "yql": f"select * from {schema} where {where}",  # noqa: S608
            "query": request.query,
            "input.query(q)": "embed(@query)",
            "ranking.profile": "hybrid",
            "hits": request.hits,
            "timeout": str(timeout),
        }

    body.update(extra_params)
    return body


def _normalize_hit(hit: dict) -> SearchResult:
    fields = hit.get("fields", {})
    return SearchResult(
        source_id=str(fields.get("source_id", "")),
        uri=str(fields.get("uri", "")),
        title=str(fields.get("title", "")),
        chunk_id=str(fields.get("chunk_id", "")),
        chunk_index=int(fields.get("chunk_index", 0)),
        text=str(fields.get("text", "")),
        relevance=float(hit.get("relevance", 0.0)),
        kind=str(fields.get("kind", "")),
    )
