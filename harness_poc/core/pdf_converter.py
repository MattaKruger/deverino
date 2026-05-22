from __future__ import annotations

import time
from pathlib import Path  # noqa: TC003

from harness_poc.core.retrieval import (
    DocumentChunk,
    compute_content_hash,
    make_chunk_id,
    make_source_id,
)


def convert_pdf_to_chunks(
    file_path: Path,
    uri: str,
    title: str,
    kind: str,
    max_tokens: int,
) -> list[DocumentChunk]:
    """Convert a PDF to DocumentChunks using docling's HybridChunker."""
    from docling.chunking import HybridChunker  # noqa: PLC0415
    from docling.document_converter import DocumentConverter  # noqa: PLC0415

    converter = DocumentConverter()
    result = converter.convert(file_path)
    doc = result.document

    chunker = HybridChunker(max_tokens=max_tokens)
    source_id = make_source_id(uri)
    now_ms = int(time.time() * 1000)
    chunks: list[DocumentChunk] = []

    for i, chunk in enumerate(chunker.chunk(doc)):
        chunk_title = _extract_chunk_title(chunk) or title
        text = chunk.text
        if not text.strip():
            continue
        chunks.append(
            DocumentChunk(
                source_id=source_id,
                uri=uri,
                title=chunk_title,
                chunk_id=make_chunk_id(source_id, i),
                chunk_index=i,
                text=text,
                kind=kind,
                content_hash=compute_content_hash(text),
                updated_at=now_ms,
            )
        )

    return chunks


def _extract_chunk_title(chunk: object) -> str:
    """Return the most specific heading from chunk metadata, or empty string."""
    try:
        headings = chunk.meta.headings  # type: ignore[union-attr]
        if headings:
            return headings[-1]
    except AttributeError:
        pass
    return ""
