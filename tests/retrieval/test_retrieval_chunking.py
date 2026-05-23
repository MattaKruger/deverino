# tests/test_retrieval_chunking.py
from __future__ import annotations

from harness_poc.core.retrieval import (
    chunk_text,
    compute_content_hash,
    make_chunk_id,
    make_document_chunks,
    make_source_id,
)


def test_chunk_text_single_when_short() -> None:
    result = chunk_text("hello world", chunk_size=100, overlap=10)
    assert result == ["hello world"]


def test_chunk_text_empty_returns_empty() -> None:
    assert chunk_text("", chunk_size=100, overlap=10) == []
    assert chunk_text("   ", chunk_size=100, overlap=10) == []


def test_chunk_text_multiple_chunks() -> None:
    text = "a" * 200
    chunks = chunk_text(text, chunk_size=100, overlap=20)
    # [0:100], [80:180], [160:200]
    assert len(chunks) == 3
    assert len(chunks[0]) == 100
    assert len(chunks[1]) == 100
    assert len(chunks[2]) == 40


def test_chunk_text_overlap_preserved() -> None:
    text = "abcdefghij"  # 10 chars
    chunks = chunk_text(text, chunk_size=6, overlap=2)
    # [0:6]="abcdef", [4:10]="efghij"
    assert chunks[0] == "abcdef"
    assert chunks[1] == "efghij"
    assert len(chunks) == 2


def test_chunk_text_exact_fit() -> None:
    text = "a" * 100
    chunks = chunk_text(text, chunk_size=100, overlap=10)
    assert chunks == [text]


def test_compute_content_hash_stable() -> None:
    h1 = compute_content_hash("hello world")
    h2 = compute_content_hash("hello world")
    assert h1 == h2
    assert len(h1) == 64  # SHA-256 hex


def test_compute_content_hash_different_inputs() -> None:
    assert compute_content_hash("abc") != compute_content_hash("xyz")


def test_make_source_id_slug() -> None:
    assert make_source_id("docs/foo.md") == "docs-foo-md"
    assert make_source_id("docs/sub/bar.yaml") == "docs-sub-bar-yaml"
    assert make_source_id("README.md") == "readme-md"


def test_make_chunk_id() -> None:
    assert make_chunk_id("docs-foo-md", 0) == "docs-foo-md-0000"
    assert make_chunk_id("docs-foo-md", 3) == "docs-foo-md-0003"
    assert make_chunk_id("docs-foo-md", 42) == "docs-foo-md-0042"


def test_make_document_chunks_assembles_correctly() -> None:
    text = "a" * 50
    chunks = make_document_chunks(
        text=text,
        uri="docs/test.md",
        title="Test",
        kind="doc",
        chunk_size=100,
        chunk_overlap=10,
    )
    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.source_id == "docs-test-md"
    assert chunk.uri == "docs/test.md"
    assert chunk.title == "Test"
    assert chunk.kind == "doc"
    assert chunk.chunk_index == 0
    assert chunk.chunk_id == "docs-test-md-0000"
    assert chunk.text == text
    assert len(chunk.content_hash) == 64
    assert chunk.updated_at > 0


def test_make_document_chunks_multiple() -> None:
    text = "x" * 200
    chunks = make_document_chunks(
        text=text,
        uri="docs/big.md",
        title="Big",
        kind="doc",
        chunk_size=100,
        chunk_overlap=20,
    )
    assert len(chunks) == 3
    assert [c.chunk_index for c in chunks] == [0, 1, 2]
    assert all(c.source_id == "docs-big-md" for c in chunks)
