from __future__ import annotations

import json
import logging
import re
import time
import urllib.request
from pathlib import Path  # noqa: TC003

from harness_poc.core.retrieval.retrieval import (
    DocumentChunk,
    compute_content_hash,
    make_chunk_id,
    make_document_chunks,
    make_source_id,
)

logger = logging.getLogger(__name__)

# Control characters illegal in Vespa string fields (keep tab, newline, CR)
_ILLEGAL_CONTROL_RE = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")


def convert_pdf_to_chunks(  # noqa: PLR0913
    file_path: Path,
    uri: str,
    title: str,
    kind: str,
    max_tokens: int,
    *,
    ocr_service_url: str | None = None,
) -> list[DocumentChunk]:
    """Convert a PDF to DocumentChunks.

    When ocr_service_url is set, delegates to the remote OCR service
    to avoid cold-starting docling/RapidOCR per file. Otherwise converts
    locally using the in-process docling converter.
    """
    if ocr_service_url:
        return _convert_remote(
            file_path=file_path,
            uri=uri,
            title=title,
            kind=kind,
            max_tokens=max_tokens,
            service_url=ocr_service_url,
        )
    return _convert_local(
        file_path=file_path,
        uri=uri,
        title=title,
        kind=kind,
        max_tokens=max_tokens,
    )


def _convert_local(
    file_path: Path,
    uri: str,
    title: str,
    kind: str,
    max_tokens: int,
) -> list[DocumentChunk]:
    """Convert a PDF to DocumentChunks.

    Uses pymupdf for near-instant text extraction from born-digital PDFs
    (arXiv papers). Falls back to docling only when pymupdf is unavailable
    or returns empty text.
    """
    text = _extract_text_pymupdf(file_path)
    if text:
        return make_document_chunks(
            text=text,
            uri=uri,
            title=title,
            kind=kind,
            chunk_size=max_tokens,
            chunk_overlap=0,
        )
    return _convert_local_docling(file_path, uri, title, kind, max_tokens)


def _extract_text_pymupdf(file_path: Path) -> str:
    """Extract embedded text from a PDF using pymupdf (fast, no ML).

    Returns the full text of the document, sanitized of control characters,
    or empty string if extraction fails.
    """
    try:
        import fitz  # noqa: PLC0415
    except ImportError:
        logger.debug("pymupdf not available, falling back to docling")
        return ""

    try:
        doc = fitz.open(file_path)
    except Exception:
        logger.debug("pymupdf cannot open %s", file_path.name)
        return ""

    pages: list[str] = []
    for page in doc:
        try:
            text = page.get_text()
            if text.strip():
                pages.append(text)
        except Exception as exc:
            logger.debug("pymupdf page text failed: %s", exc)
            continue
    doc.close()
    raw = "\n\n".join(pages)
    # Strip control chars illegal in Vespa string fields (keep tab, newline, CR)
    return _ILLEGAL_CONTROL_RE.sub(" ", raw)


def _convert_local_docling(
    file_path: Path,
    uri: str,
    title: str,
    kind: str,
    max_tokens: int,
) -> list[DocumentChunk]:
    """Convert a PDF to DocumentChunks using in-process docling (slow, ML-heavy)."""
    from docling.chunking import HybridChunker  # noqa: PLC0415
    from docling.datamodel.base_models import InputFormat  # noqa: PLC0415
    from docling.datamodel.pipeline_options import (  # noqa: PLC0415
        AcceleratorDevice,
        AcceleratorOptions,
        PdfPipelineOptions,
    )
    from docling.document_converter import DocumentConverter, PdfFormatOption  # noqa: PLC0415
    from docling_core.transforms.chunker.hybrid_chunker import (  # noqa: PLC0415
        get_default_tokenizer,
    )
    from docling_core.transforms.chunker.tokenizer.huggingface import (  # noqa: PLC0415
        HuggingFaceTokenizer,
    )

    pipeline_options = PdfPipelineOptions()
    pipeline_options.accelerator_options = AcceleratorOptions(device=AcceleratorDevice.CPU)
    pipeline_options.do_ocr = False  # born-digital PDFs have embedded text; skip OCR
    converter = DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)}
    )
    result = converter.convert(file_path)
    doc = result.document

    default_tokenizer = get_default_tokenizer()
    tokenizer = HuggingFaceTokenizer(tokenizer=default_tokenizer.tokenizer, max_tokens=max_tokens)
    chunker = HybridChunker(tokenizer=tokenizer)
    source_id = make_source_id(uri)
    now_ms = int(time.time() * 1000)
    chunks: list[DocumentChunk] = []

    out_index = 0
    for chunk in chunker.chunk(doc):
        chunk_title = _extract_chunk_title(chunk) or title
        text = chunk.text or ""
        if not text.strip():
            continue
        chunks.append(
            DocumentChunk(
                source_id=source_id,
                uri=uri,
                title=chunk_title,
                chunk_id=make_chunk_id(source_id, out_index),
                chunk_index=out_index,
                text=text,
                kind=kind,
                content_hash=compute_content_hash(text),
                updated_at=now_ms,
            )
        )
        out_index += 1

    return chunks


def _extract_chunk_title(chunk: object) -> str:
    """Return the most specific heading from chunk metadata, or empty string."""
    meta = getattr(chunk, "meta", None)
    headings = getattr(meta, "headings", None)
    if isinstance(headings, list) and headings:
        return str(headings[-1])
    logger.debug("chunk.meta.headings not available; falling back to file title")
    return ""


def _convert_remote(  # noqa: PLR0913
    file_path: Path,
    uri: str,
    title: str,
    kind: str,
    max_tokens: int,
    service_url: str,
) -> list[DocumentChunk]:
    """Convert a PDF via the remote OCR service."""
    payload = json.dumps(
        {
            "file_path": str(file_path),
            "uri": uri,
            "title": title,
            "kind": kind,
            "max_tokens": max_tokens,
        }
    ).encode("utf-8")

    req = urllib.request.Request(  # noqa: S310
        f"{service_url.rstrip('/')}/convert",
        data=payload,
        headers={"Content-Type": "application/json"},
    )

    with urllib.request.urlopen(req, timeout=300) as resp:  # noqa: S310
        data = json.loads(resp.read().decode("utf-8"))

    return [DocumentChunk(**c) for c in data]
