from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from harness_poc.core.config import RetrievalConfig
from harness_poc.core.retrieval import (
    FeedSummary,
    LiveVespaDocumentClient,
    SearchRequest,
    SearchResult,
    VespaDocumentClient,
    _build_query_body,
    _normalize_hit,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from harness_poc.core.retrieval import DocumentChunk

pytestmark = pytest.mark.integration


class FakeVespaClient:
    """In-memory Vespa substitute for unit tests."""

    def __init__(self, *, healthy: bool = True) -> None:
        self._healthy = healthy
        self._docs: dict[str, DocumentChunk] = {}
        self.fed_ids: list[str] = []
        self.deleted_sources: list[str] = []

    def health_check(self) -> None:
        if not self._healthy:
            msg = "Vespa unavailable"
            raise RuntimeError(msg)

    def feed_chunks(self, chunks: Iterable[DocumentChunk]) -> FeedSummary:
        fed = 0
        for chunk in chunks:
            self._docs[chunk.chunk_id] = chunk
            self.fed_ids.append(chunk.chunk_id)
            fed += 1
        return FeedSummary(fed=fed, failed=0, failed_ids=[])

    def delete_source(self, source_id: str) -> None:
        self.deleted_sources.append(source_id)
        to_delete = [key for key, chunk in self._docs.items() if chunk.source_id == source_id]
        for key in to_delete:
            del self._docs[key]

    def search(self, request: SearchRequest) -> list[SearchResult]:
        results = [
            SearchResult(
                source_id=chunk.source_id,
                uri=chunk.uri,
                title=chunk.title,
                chunk_id=chunk.chunk_id,
                chunk_index=chunk.chunk_index,
                text=chunk.text,
                relevance=1.0,
                kind=chunk.kind,
            )
            for chunk in self._docs.values()
            if request.query.lower() in chunk.text.lower()
        ]
        return results[: request.hits]


def test_fake_client_satisfies_protocol() -> None:
    assert isinstance(FakeVespaClient(), VespaDocumentClient)


def test_live_client_satisfies_protocol() -> None:
    client = LiveVespaDocumentClient(RetrievalConfig())
    assert isinstance(client, VespaDocumentClient)


def test_build_query_body_keyword() -> None:
    req = SearchRequest(query="state machine", mode="keyword", hits=5)
    body = _build_query_body(req, schema="doc_chunk", timeout=5)
    assert body["ranking.profile"] == "keyword"
    assert "@query" in body["yql"]
    assert "nearestNeighbor" not in body["yql"]
    assert body["query"] == "state machine"
    assert body["hits"] == 5


def test_build_query_body_semantic() -> None:
    req = SearchRequest(query="how memory works", mode="semantic", hits=8)
    body = _build_query_body(req, schema="doc_chunk", timeout=5)
    assert body["ranking.profile"] == "semantic"
    assert "nearestNeighbor" in body["yql"]
    assert body["input.query(q)"] == "embed(@query)"
    assert "text(@query)" not in body["yql"]


def test_build_query_body_hybrid() -> None:
    req = SearchRequest(query="memory", mode="hybrid", hits=8)
    body = _build_query_body(req, schema="doc_chunk", timeout=5)
    assert body["ranking.profile"] == "hybrid"
    assert "nearestNeighbor" in body["yql"]
    assert "text(@query)" in body["yql"]


def test_build_query_body_source_filter() -> None:
    req = SearchRequest(query="x", mode="keyword", hits=5, source_id="docs-foo-md")
    body = _build_query_body(req, schema="doc_chunk", timeout=5)
    assert body["filter_source_id"] == "docs-foo-md"
    assert "@filter_source_id" in body["yql"]


def test_build_query_body_kind_filter() -> None:
    req = SearchRequest(query="x", mode="keyword", hits=5, kind="spec")
    body = _build_query_body(req, schema="doc_chunk", timeout=5)
    assert body["filter_kind"] == "spec"


def test_normalize_hit_extracts_fields() -> None:
    raw_hit = {
        "id": "id:deverino:doc_chunk::docs-foo-md-0001",
        "relevance": 0.87,
        "fields": {
            "source_id": "docs-foo-md",
            "uri": "docs/foo.md",
            "title": "Foo",
            "chunk_id": "docs-foo-md-0001",
            "chunk_index": 1,
            "text": "Some text here.",
            "kind": "doc",
        },
    }
    result = _normalize_hit(raw_hit)
    assert result.source_id == "docs-foo-md"
    assert result.uri == "docs/foo.md"
    assert result.relevance == pytest.approx(0.87)
    assert result.chunk_index == 1


def test_normalize_hit_missing_fields_defaults() -> None:
    raw_hit = {"id": "id:ns:schema::x", "relevance": 0.0, "fields": {}}
    result = _normalize_hit(raw_hit)
    assert result.source_id == ""
    assert result.text == ""
    assert result.relevance == 0.0
