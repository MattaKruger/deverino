# Docling PDF Pipeline

**Date:** 2026-05-22
**Status:** Draft

## Problem

The current PDF indexing path uses `pypdf.extract_text()` — a low-fidelity page dump. It loses:

- Heading hierarchy (everything is flat text)
- Table structure (rows become garbled space-separated strings)
- Multi-column layouts (columns interleave incorrectly)
- Paragraph boundaries (no semantic boundaries for the chunker to respect)

The downstream character-based chunker (`chunk_text` in `retrieval.py`) splits at fixed character boundaries with no awareness of document structure. A section heading and its body frequently land in different chunks. Tables are split mid-row. Both LLM retrieval quality and human readability of search results suffer.

## Goal

Replace the pypdf extraction + character chunking path for PDFs with:

1. **Docling conversion** — converts PDF to a structured `DoclingDocument` (markdown-serialisable, table-aware, OCR-capable for scanned pages)
2. **`HybridChunker`** — docling's built-in chunker that respects heading boundaries, paragraph boundaries, and table atomicity

Non-PDF formats (`.md`, `.txt`, `.py`, etc.) are unaffected. The Vespa schema, DB schema, skill interface, and config surface are unchanged.

## Scope

### In scope

- Replace `_read_pdf_text` in `document_index.py` with a docling-based converter
- Replace the `chunk_text` call for PDFs with `HybridChunker`
- Add `docling` to `pyproject.toml` dependencies, remove `pypdf`
- Preserve the existing `DocumentChunk` dataclass as the output contract
- Pass `chunk_size_chars` config value to `HybridChunker` as a `max_tokens` hint
- Preserve chunk `title` enrichment: use the nearest heading from docling's chunk metadata when available, fall back to filename stem

### Out of scope

- Vespa schema changes (no new fields)
- Metadata fields (authors, abstract) — deferred to a follow-on phase
- Non-PDF format changes
- Config UI changes (chunk size reuse is sufficient)

## Design

### Dependencies

Remove `pypdf>=6.11.0` from `pyproject.toml`. Add:

```toml
"docling>=2.0.0",
```

Docling bundles its own PDF backend (based on `pdfminer` + `pypdfium2`) and downloads EasyOCR / layout models on first use. No other changes to `pyproject.toml`.

### New module: `harness_poc/core/pdf_converter.py`

Isolate all docling imports here so the rest of the codebase stays importable even if docling is not installed (useful for tests that mock the converter).

```python
# harness_poc/core/pdf_converter.py

from pathlib import Path
from harness_poc.core.retrieval import DocumentChunk, make_source_id, make_chunk_id, compute_content_hash
import time

def convert_pdf_to_chunks(
    file_path: Path,
    uri: str,
    title: str,
    kind: str,
    max_tokens: int,
) -> list[DocumentChunk]:
    """Convert a PDF to DocumentChunks using docling's HybridChunker."""
    from docling.document_converter import DocumentConverter
    from docling.chunking import HybridChunker

    converter = DocumentConverter()
    result = converter.convert(file_path)
    doc = result.document

    chunker = HybridChunker(max_tokens=max_tokens)
    source_id = make_source_id(uri)
    now_ms = int(time.time() * 1000)
    chunks = []

    for i, chunk in enumerate(chunker.chunk(doc)):
        # Use heading from chunk metadata if available, else fall back to title
        chunk_title = _extract_chunk_title(chunk) or title
        text = chunk.text
        if not text.strip():
            continue
        chunks.append(DocumentChunk(
            source_id=source_id,
            uri=uri,
            title=chunk_title,
            chunk_id=make_chunk_id(source_id, i),
            chunk_index=i,
            text=text,
            kind=kind,
            content_hash=compute_content_hash(text),
            updated_at=now_ms,
        ))

    return chunks


def _extract_chunk_title(chunk) -> str:
    """Extract the nearest heading from docling chunk metadata."""
    try:
        headings = chunk.meta.headings
        if headings:
            return headings[-1]  # most specific heading
    except AttributeError:
        pass
    return ""
```

### Changes to `document_index.py`

1. Remove `from pypdf import PdfReader` and `from pypdf.errors import PdfReadError`
2. Remove `_read_pdf_text` function
3. In `_index_one_isolated`, replace:
   ```python
   text = _sanitize_text(_read_document_text(file_path))
   ...
   chunks = make_document_chunks(text=text, ...)
   ```
   with a branch:
   ```python
   if file_path.suffix.lower() == ".pdf":
       chunks = convert_pdf_to_chunks(
           file_path=file_path,
           uri=uri,
           title=title,
           kind=_infer_kind(uri),
           max_tokens=self._config.chunk_size_chars,
       )
       # content hash over concatenated chunk texts for change detection
       content_hash = compute_content_hash("".join(c.text for c in chunks))
   else:
       text = _sanitize_text(_read_document_text(file_path))
       content_hash = compute_content_hash(text)
       chunks = make_document_chunks(text=text, uri=uri, title=title,
                                     kind=_infer_kind(uri),
                                     chunk_size=self._config.chunk_size_chars,
                                     chunk_overlap=self._config.chunk_overlap_chars)
   ```
4. Update exception handling: catch `Exception` broadly for the PDF branch (docling raises varied errors), log and return `_FileResult(status="failed", ...)`.
5. Remove `PdfReadError` from the except clause in the non-PDF branch.

### Content hash for change detection

For PDFs, the content hash is computed over the **concatenated text of all chunks** (same sha256 function). This preserves the existing skip-if-unchanged behaviour: if the PDF changes, its hash changes and it is re-indexed.

### Error handling

- If docling conversion fails (corrupt PDF, unsupported encoding, model download failure), return `_FileResult(status="failed", ...)` with the exception message — consistent with the current pypdf behaviour.
- If docling produces zero chunks (blank PDF), treat as `failed` with message `"no content extracted"`.

## Test plan

| Test | Approach |
|------|----------|
| PDF produces semantically coherent chunks | Unit test with a small fixture PDF; assert no chunk splits mid-sentence |
| Table content is kept atomic | Fixture PDF with a table; assert table rows appear in one chunk |
| Scanned PDF (image-only) falls back to OCR | Fixture scanned PDF; assert non-empty chunks returned |
| Hash-based deduplication still works | Index same PDF twice; assert second run returns `skipped` |
| Non-PDF files unchanged | Index a `.md` file; assert existing character chunker is used |
| Docling import error is caught gracefully | Mock `DocumentConverter` to raise; assert `failed` result |
| Zero-content PDF returns `failed` | Fixture blank PDF; assert `failed` with `"no content extracted"` |

Existing tests for non-PDF indexing paths must continue to pass unchanged.

## Migration notes

- Re-indexing existing PDFs: run `uv run harness-poc documents index <path> --force` to regenerate chunks with docling. Old pypdf-based chunks are replaced (Vespa delete-then-feed is already implemented in `DocumentIndexer`).
- First run downloads docling layout models (~1.5 GB). This is a one-time cost. Set `DOCLING_ARTIFACTS_PATH` to control the cache location.
- `chunk_size_chars` is reused as `max_tokens` for `HybridChunker`. The semantics differ slightly (chars vs tokens), but docling's chunker treats it as a soft upper bound so existing config values are safe to reuse without tuning.
