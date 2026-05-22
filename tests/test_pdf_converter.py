from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

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
    fake_hybrid_chunker = MagicMock(return_value=fake_chunker_instance)

    fake_doc = MagicMock()
    fake_result = MagicMock()
    fake_result.document = fake_doc
    fake_converter_instance = MagicMock()
    fake_converter_instance.convert.return_value = fake_result
    fake_document_converter = MagicMock(return_value=fake_converter_instance)
    fake_default_tokenizer = MagicMock()
    fake_default_tokenizer.tokenizer = MagicMock()
    fake_huggingface_tokenizer = MagicMock()
    fake_huggingface_tokenizer.side_effect = lambda **kwargs: MagicMock(
        max_tokens=kwargs["max_tokens"]
    )

    return {
        "docling": MagicMock(),
        "docling.document_converter": MagicMock(
            DocumentConverter=fake_document_converter,
            PdfFormatOption=MagicMock(),
        ),
        "docling.chunking": MagicMock(HybridChunker=fake_hybrid_chunker),
        "docling.datamodel": MagicMock(),
        "docling.datamodel.base_models": MagicMock(),
        "docling.datamodel.pipeline_options": MagicMock(),
        "docling_core": MagicMock(),
        "docling_core.transforms": MagicMock(),
        "docling_core.transforms.chunker": MagicMock(),
        "docling_core.transforms.chunker.hybrid_chunker": MagicMock(
            get_default_tokenizer=MagicMock(return_value=fake_default_tokenizer),
        ),
        "docling_core.transforms.chunker.tokenizer": MagicMock(),
        "docling_core.transforms.chunker.tokenizer.huggingface": MagicMock(
            HuggingFaceTokenizer=fake_huggingface_tokenizer,
        ),
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
    assert chunks[0].chunk_index == 0  # contiguous from 0, not 1


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

    expected = hashlib.sha256(b"Hello world.").hexdigest()
    assert chunks[0].content_hash == expected


def test_hybridchunker_receives_tokenizer_with_max_tokens(tmp_path: Path) -> None:
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-fake")

    mods = _fake_docling([("Some text.", [])])
    fake_hybrid_chunker = mods["docling.chunking"].HybridChunker
    with patch.dict(sys.modules, mods):
        convert_pdf_to_chunks(pdf, "paper.pdf", "Paper", "doc", 1024)

    fake_hybrid_chunker.assert_called_once()
    tokenizer = fake_hybrid_chunker.call_args.kwargs["tokenizer"]
    assert tokenizer.max_tokens == 1024
