# harness_poc/core/retrieval.py
from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Iterable


@dataclass(frozen=True, slots=True)
class DocumentChunk:
    source_id: str
    uri: str
    title: str
    chunk_id: str
    chunk_index: int
    text: str
    kind: str
    content_hash: str
    updated_at: int  # milliseconds since epoch


@dataclass(frozen=True, slots=True)
class SearchResult:
    source_id: str
    uri: str
    title: str
    chunk_id: str
    chunk_index: int
    text: str
    relevance: float
    kind: str


@dataclass(frozen=True, slots=True)
class SearchRequest:
    query: str
    mode: str  # hybrid | semantic | keyword
    hits: int
    source_id: str | None = None
    kind: str | None = None


@dataclass(frozen=True, slots=True)
class FeedSummary:
    fed: int
    failed: int
    failed_ids: list[str]


@runtime_checkable
class VespaDocumentClient(Protocol):
    def health_check(self) -> None: ...
    def feed_chunks(self, chunks: Iterable[DocumentChunk]) -> FeedSummary: ...
    def delete_source(self, source_id: str) -> None: ...
    def search(self, request: SearchRequest) -> list[SearchResult]: ...


def make_source_id(uri: str) -> str:
    """Convert a URI path to a URL-safe slug. e.g. 'docs/foo.md' -> 'docs-foo-md'."""
    return re.sub(r"-+", "-", re.sub(r"[/\\.:]", "-", uri)).strip("-").lower()


def make_chunk_id(source_id: str, chunk_index: int) -> str:
    return f"{source_id}-{chunk_index:04d}"


def compute_content_hash(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


def chunk_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    if not text.strip():
        return []
    if len(text) <= chunk_size:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunks.append(text[start:end])
        if end == len(text):
            break
        start = end - overlap
    return chunks


def make_document_chunks(  # noqa: PLR0913
    text: str,
    uri: str,
    title: str,
    kind: str,
    chunk_size: int,
    chunk_overlap: int,
) -> list[DocumentChunk]:
    source_id = make_source_id(uri)
    now_ms = int(time.time() * 1000)
    raw_chunks = chunk_text(text, chunk_size, chunk_overlap)
    return [
        DocumentChunk(
            source_id=source_id,
            uri=uri,
            title=title,
            chunk_id=make_chunk_id(source_id, i),
            chunk_index=i,
            text=chunk,
            kind=kind,
            content_hash=compute_content_hash(chunk),
            updated_at=now_ms,
        )
        for i, chunk in enumerate(raw_chunks)
    ]
