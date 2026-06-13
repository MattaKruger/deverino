# Docling PDF Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace pypdf + character chunker for PDFs with docling `DocumentConverter` + `HybridChunker` for structure-aware, heading- and table-respecting chunk extraction.

**Architecture:** New isolated `pdf_converter.py` module handles all docling logic; `document_index.py` branches on `.pdf` extension to call it instead of the old `_read_pdf_text` + `make_document_chunks` path. Docling imports are lazy (inside the function body) so the rest of the codebase stays importable without docling installed. Non-PDF formats are unchanged.

**Tech Stack:** `docling>=2.0.0` (`DocumentConverter`, `HybridChunker`); `pypdf` removed.

---

## File map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `harness_poc/core/pdf_converter.py` | Docling conversion + chunking, isolated imports |
| Modify | `harness_poc/core/document_index.py` | Remove pypdf, import converter, branch PDF vs non-PDF |
| Modify | `pyproject.toml` | Swap `pypdf>=6.11.0` → `docling>=2.0.0` |
| Create | `tests/test_pdf_converter.py` | Unit tests for pdf_converter (mock docling) |
| Modify | `tests/test_document_index.py` | Replace pypdf-based PDF test with converter-mocked tests |

---

## Task 1: Swap pypdf for docling in pyproject.toml

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Edit pyproject.toml**

In `pyproject.toml`, in the `dependencies` list, find:
```toml
"pypdf>=6.11.0",
```
Replace with:
```toml
"docling>=2.0.0",
```

- [ ] **Step 2: Sync dependencies**

Run: `uv sync`

Expected: resolves and installs docling and transitive deps. The docling **package** installs (pdfminer, pypdfium2, etc.); OCR/layout models are NOT downloaded here — they download on first `DocumentConverter().convert()` call.

- [ ] **Step 3: Verify docling imports**

Run: `uv run python -c "from docling.document_converter import DocumentConverter; from docling.chunking import HybridChunker; print('ok')"`

Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: replace pypdf with docling>=2.0.0"
```

---

## Task 2: Create `harness_poc/core/pdf_converter.py` (TDD)

**Files:**
- Create: `tests/test_pdf_converter.py`
- Create: `harness_poc/core/pdf_converter.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_pdf_converter.py` with this content:

```python
from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from harness_poc.core.pdf_converter import convert_pdf_to_chunks


def _fake_docling(chunks_data: list[tuple[str, list[str]]]) -> dict:
    """Build sys.modules patches with fake docling chunks.

    chunks_data: list of (text, headings) pairs, one per chunk.
    """
    fake_chunks = []
    for text, headings in chunks_data:
        c = MagicMock()
        c.text = text
        c.meta.headings = headings
        fake_chunks.append(c)

    fake_chunker_instance = MagicMock()
    fake_chunker_instance.chunk.return_value = fake_chunks
    FakeHybridChunker = MagicMock(return_value=fake_chunker_instance)

    fake_doc = MagicMock()
    fake_result = MagicMock()
    fake_result.document = fake_doc
    fake_converter_instance = MagicMock()
    fake_converter_instance.convert.return_value = fake_result
    FakeDocumentConverter = MagicMock(return_value=fake_converter_instance)

    return {
        "docling": MagicMock(),
        "docling.document_converter": MagicMock(DocumentConverter=FakeDocumentConverter),
        "docling.chunking": MagicMock(HybridChunker=FakeHybridChunker),
    }


def test_convert_produces_document_chunks(tmp_path: Path) -> None:
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-fake")

    mods = _fake_docling([
        ("Introduction text.", ["Introduction"]),
        ("Methods section.", []),
    ])
    with patch.dict(sys.modules, mods):
        chunks = convert_pdf_to_chunks(pdf, "docs/paper.pdf", "Paper", "doc", 512)

    assert len(chunks) == 2
    assert chunks[0].title == "Introduction"
    assert chunks[0].text == "Introduction text."
    assert chunks[0].kind == "doc"
    assert chunks[0].chunk_index == 0
    assert chunks[0].uri == "docs/paper.pdf"
    assert chunks[1].title == "Paper"  # falls back to provided title when no heading
    assert chunks[1].chunk_index == 1


def test_empty_text_chunks_are_skipped(tmp_path: Path) -> None:
    pdf = tmp_path / "sparse.pdf"
    pdf.write_bytes(b"%PDF-fake")

    mods = _fake_docling([("   ", []), ("Real content.", ["Results"])])
    with patch.dict(sys.modules, mods):
        chunks = convert_pdf_to_chunks(pdf, "sparse.pdf", "Sparse", "source", 512)

    assert len(chunks) == 1
    assert chunks[0].text == "Real content."


def test_heading_fallback_uses_provided_title(tmp_path: Path) -> None:
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-fake")

    mods = _fake_docling([("Body text.", [])])
    with patch.dict(sys.modules, mods):
        chunks = convert_pdf_to_chunks(pdf, "paper.pdf", "My Title", "doc", 512)

    assert chunks[0].title == "My Title"


def test_most_specific_heading_is_used(tmp_path: Path) -> None:
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-fake")

    mods = _fake_docling([("Content.", ["Chapter 1", "Section 1.2"])])
    with patch.dict(sys.modules, mods):
        chunks = convert_pdf_to_chunks(pdf, "paper.pdf", "Paper", "doc", 512)

    assert chunks[0].title == "Section 1.2"


def test_content_hash_matches_chunk_text(tmp_path: Path) -> None:
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-fake")

    mods = _fake_docling([("Hello world.", ["Intro"])])
    with patch.dict(sys.modules, mods):
        chunks = convert_pdf_to_chunks(pdf, "paper.pdf", "Paper", "doc", 512)

    expected = hashlib.sha256("Hello world.".encode()).hexdigest()
    assert chunks[0].content_hash == expected


def test_hybridchunker_receives_max_tokens(tmp_path: Path) -> None:
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-fake")

    fake_chunk = MagicMock()
    fake_chunk.text = "Some text."
    fake_chunk.meta.headings = []
    fake_chunker_instance = MagicMock()
    fake_chunker_instance.chunk.return_value = [fake_chunk]
    FakeHybridChunker = MagicMock(return_value=fake_chunker_instance)

    fake_doc = MagicMock()
    fake_result = MagicMock()
    fake_result.document = fake_doc
    fake_converter_instance = MagicMock()
    fake_converter_instance.convert.return_value = fake_result
    FakeDocumentConverter = MagicMock(return_value=fake_converter_instance)

    mods = {
        "docling": MagicMock(),
        "docling.document_converter": MagicMock(DocumentConverter=FakeDocumentConverter),
        "docling.chunking": MagicMock(HybridChunker=FakeHybridChunker),
    }
    with patch.dict(sys.modules, mods):
        convert_pdf_to_chunks(pdf, "paper.pdf", "Paper", "doc", 1024)

    FakeHybridChunker.assert_called_once_with(max_tokens=1024)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_pdf_converter.py -v`

Expected: `ModuleNotFoundError: No module named 'harness_poc.core.pdf_converter'` — all 6 tests fail with import error.

- [ ] **Step 3: Implement `harness_poc/core/pdf_converter.py`**

Create `harness_poc/core/pdf_converter.py`:

```python
from __future__ import annotations

import time
from pathlib import Path

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_pdf_converter.py -v`

Expected: All 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add harness_poc/core/pdf_converter.py tests/test_pdf_converter.py
git commit -m "feat: add pdf_converter module with docling HybridChunker"
```

---

## Task 3: Update `document_index.py` and its tests

**Files:**
- Modify: `harness_poc/core/document_index.py`
- Modify: `tests/test_document_index.py`

- [ ] **Step 1: Write the new PDF tests in `test_document_index.py`**

Open `tests/test_document_index.py`. Add these imports at the top of the file (after the existing imports):

```python
from harness_poc.core.retrieval import compute_content_hash, make_chunk_id, make_source_id
from harness_poc.core.retrieval import DocumentChunk
```

Find and **replace** the existing `test_index_pdf_file` function (the one that creates `FakePage`, `FakePdfReader`, and patches `document_index.PdfReader`) with these three tests:

```python
def test_index_pdf_file(
    db_engine: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = tmp_path / "guide.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")

    source_id = make_source_id("guide.pdf")
    fake_chunks = [
        DocumentChunk(
            source_id=source_id,
            uri="guide.pdf",
            title="Introduction",
            chunk_id=make_chunk_id(source_id, 0),
            chunk_index=0,
            text="Content about Vespa document indexing.",
            kind="source",
            content_hash=compute_content_hash("Content about Vespa document indexing."),
            updated_at=1_000_000,
        )
    ]

    monkeypatch.setattr(
        document_index, "convert_pdf_to_chunks", lambda **_kw: fake_chunks
    )

    db = BlackboardDatabase(db_engine)
    vespa = FakeVespaClient()
    indexer = _make_indexer(db, vespa)

    result = indexer.index_paths(project_root=tmp_path, paths=["guide.pdf"])

    assert result.indexed == 1
    assert result.skipped == 0
    assert result.failed == 0
    assert result.chunks_indexed == 1
    fed_text = "\n".join(chunk.text for chunk in vespa._docs.values())
    assert "Vespa document indexing" in fed_text


def test_index_blank_pdf_returns_failed(
    db_engine: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = tmp_path / "blank.pdf"
    pdf.write_bytes(b"%PDF-1.4 blank")

    monkeypatch.setattr(document_index, "convert_pdf_to_chunks", lambda **_kw: [])

    db = BlackboardDatabase(db_engine)
    vespa = FakeVespaClient()
    indexer = _make_indexer(db, vespa)

    result = indexer.index_paths(project_root=tmp_path, paths=["blank.pdf"])

    assert result.failed == 1
    assert result.indexed == 0
    assert any("no content extracted" in f["error"] for f in result.failures)


def test_index_pdf_conversion_error_returns_failed(
    db_engine: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = tmp_path / "corrupt.pdf"
    pdf.write_bytes(b"not a pdf")

    def _raise(**_kw: object) -> list[DocumentChunk]:
        raise RuntimeError("PDF conversion failed")

    monkeypatch.setattr(document_index, "convert_pdf_to_chunks", _raise)

    db = BlackboardDatabase(db_engine)
    vespa = FakeVespaClient()
    indexer = _make_indexer(db, vespa)

    result = indexer.index_paths(project_root=tmp_path, paths=["corrupt.pdf"])

    assert result.failed == 1
    assert any("PDF conversion failed" in f["error"] for f in result.failures)
```

- [ ] **Step 2: Run new tests to verify they fail**

Run: `uv run pytest tests/test_document_index.py::test_index_pdf_file tests/test_document_index.py::test_index_blank_pdf_returns_failed tests/test_document_index.py::test_index_pdf_conversion_error_returns_failed -v`

Expected: All three FAIL — `AttributeError: <module 'harness_poc.core.document_index'> does not have attribute 'convert_pdf_to_chunks'`.

- [ ] **Step 3: Update imports in `document_index.py`**

In `harness_poc/core/document_index.py`, replace lines 13–14:

```python
from pypdf import PdfReader
from pypdf.errors import PdfReadError
```

with:

```python
from harness_poc.core.pdf_converter import convert_pdf_to_chunks
```

- [ ] **Step 4: Restructure `_index_one_isolated` in `document_index.py`**

Replace the entire body of `_index_one_isolated` (method starting at line 205) with:

```python
    def _index_one_isolated(  # noqa: PLR0911
        self,
        file_path: Path,
        uri: str,
        *,
        force: bool,
    ) -> _FileResult:
        """Index a single file and return its outcome without mutating shared state."""
        source_id = make_source_id(uri)

        if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            return _FileResult(uri=uri, status="skipped", skipped=1)

        if _is_secret_file(file_path.name):
            return _FileResult(uri=uri, status="skipped", skipped=1)

        title = file_path.stem.replace("-", " ").replace("_", " ").title()

        if file_path.suffix.lower() == ".pdf":
            try:
                if file_path.stat().st_size > self._config.max_file_bytes:
                    return _FileResult(
                        uri=uri,
                        status="failed",
                        failed=1,
                        failure={
                            "uri": uri,
                            "error": f"file exceeds {self._config.max_file_bytes} bytes",
                        },
                    )
                chunks = convert_pdf_to_chunks(
                    file_path=file_path,
                    uri=uri,
                    title=title,
                    kind=_infer_kind(uri),
                    max_tokens=self._config.chunk_size_chars,
                )
            except Exception as exc:
                return _FileResult(
                    uri=uri,
                    status="failed",
                    failed=1,
                    failure={"uri": uri, "error": str(exc)},
                )
            if not chunks:
                return _FileResult(
                    uri=uri,
                    status="failed",
                    failed=1,
                    failure={"uri": uri, "error": "no content extracted"},
                )
            content_hash = compute_content_hash("".join(c.text for c in chunks))
            existing = self._db.get_document_source(source_id)
            if existing is not None and existing.content_hash == content_hash and not force:
                self._db.upsert_document_source(
                    _make_db_source(
                        source_id=source_id,
                        uri=uri,
                        content_hash=content_hash,
                        status="skipped",
                        chunk_count=existing.chunk_count,
                        title=existing.title,
                        indexed_at=existing.indexed_at,
                    )
                )
                return _FileResult(uri=uri, status="skipped", skipped=1)
        else:
            try:
                if file_path.stat().st_size > self._config.max_file_bytes:
                    return _FileResult(
                        uri=uri,
                        status="failed",
                        failed=1,
                        failure={
                            "uri": uri,
                            "error": f"file exceeds {self._config.max_file_bytes} bytes",
                        },
                    )
                text = _sanitize_text(_read_document_text(file_path))
            except (OSError, UnicodeError) as exc:
                return _FileResult(
                    uri=uri,
                    status="failed",
                    failed=1,
                    failure={"uri": uri, "error": str(exc)},
                )
            content_hash = compute_content_hash(text)
            existing = self._db.get_document_source(source_id)
            if existing is not None and existing.content_hash == content_hash and not force:
                self._db.upsert_document_source(
                    _make_db_source(
                        source_id=source_id,
                        uri=uri,
                        content_hash=content_hash,
                        status="skipped",
                        chunk_count=existing.chunk_count,
                        title=existing.title,
                        indexed_at=existing.indexed_at,
                    )
                )
                return _FileResult(uri=uri, status="skipped", skipped=1)
            chunks = make_document_chunks(
                text=text,
                uri=uri,
                title=title,
                kind=_infer_kind(uri),
                chunk_size=self._config.chunk_size_chars,
                chunk_overlap=self._config.chunk_overlap_chars,
            )

        self._db.upsert_document_source(
            _make_db_source(
                source_id=source_id,
                uri=uri,
                content_hash=content_hash,
                status="pending",
                chunk_count=len(chunks),
                title=title,
            )
        )

        if existing is not None:
            self._vespa.delete_source(source_id)

        feed_summary = self._vespa.feed_chunks(chunks)
        if feed_summary.failed > 0:
            error_msg = f"{feed_summary.failed} chunk(s) failed to feed"
            self._db.upsert_document_source(
                _make_db_source(
                    source_id=source_id,
                    uri=uri,
                    content_hash=content_hash,
                    status="failed",
                    chunk_count=len(chunks),
                    title=title,
                    error=error_msg,
                )
            )
            return _FileResult(
                uri=uri,
                status="failed",
                failed=1,
                failure={"uri": uri, "error": error_msg},
            )

        now = _utc_now()
        for chunk in chunks:
            self._db.upsert_document_chunk(
                DbDocumentChunk(
                    chunk_id=chunk.chunk_id,
                    source_id=chunk.source_id,
                    chunk_index=chunk.chunk_index,
                    content_hash=chunk.content_hash,
                    vespa_id=chunk.chunk_id,
                    indexed_at=now,
                )
            )

        self._db.upsert_document_source(
            _make_db_source(
                source_id=source_id,
                uri=uri,
                content_hash=content_hash,
                status="indexed",
                chunk_count=len(chunks),
                title=title,
                indexed_at=now,
            )
        )
        return _FileResult(
            uri=uri,
            status="indexed",
            indexed=1,
            chunks=len(chunks),
        )
```

- [ ] **Step 5: Remove `_read_pdf_text` and clean up `_read_document_text`**

In `document_index.py`, replace the `_read_document_text` function:

```python
def _read_document_text(file_path: Path) -> str:
    if file_path.suffix.lower() == ".pdf":
        return _read_pdf_text(file_path)
    return file_path.read_text(encoding="utf-8", errors="replace")
```

with:

```python
def _read_document_text(file_path: Path) -> str:
    return file_path.read_text(encoding="utf-8", errors="replace")
```

Then delete the `_read_pdf_text` function entirely:

```python
def _read_pdf_text(file_path: Path) -> str:
    page_texts: list[str] = []
    with file_path.open("rb") as pdf_file:
        reader = PdfReader(pdf_file)
        for page_number, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            if text.strip():
                page_texts.append(f"[Page {page_number}]\n{text.strip()}")
    return "\n\n".join(page_texts)
```

- [ ] **Step 6: Run the new PDF tests**

Run: `uv run pytest tests/test_document_index.py::test_index_pdf_file tests/test_document_index.py::test_index_blank_pdf_returns_failed tests/test_document_index.py::test_index_pdf_conversion_error_returns_failed -v`

Expected: All three PASS.

- [ ] **Step 7: Run the full document_index test suite**

Run: `uv run pytest tests/test_document_index.py -v`

Expected: All tests PASS. Non-PDF tests (markdown, skip, force, secret files, etc.) unchanged.

- [ ] **Step 8: Run the full test suite**

Run: `uv run pytest -v`

Expected: All tests PASS. No regressions in other modules.

- [ ] **Step 9: Lint**

Run: `uv run ruff check harness_poc/core/document_index.py harness_poc/core/pdf_converter.py tests/test_pdf_converter.py tests/test_document_index.py`

Expected: No errors. If ruff flags `BLE001` (broad exception `except Exception`) on the PDF branch, add `# noqa: BLE001` to that line — catching broad exceptions is intentional here per the spec.

- [ ] **Step 10: Commit**

```bash
git add harness_poc/core/document_index.py tests/test_document_index.py
git commit -m "feat: integrate docling PDF conversion into document indexer"
```
