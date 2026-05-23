from __future__ import annotations

import logging
import time
from pathlib import Path  # noqa: TC003

from harness_poc.core.retrieval.retrieval import (
    DocumentChunk,
    compute_content_hash,
    make_chunk_id,
    make_source_id,
)

logger = logging.getLogger(__name__)


def convert_pdf_to_chunks(
    file_path: Path,
    uri: str,
    title: str,
    kind: str,
    max_tokens: int,
) -> list[DocumentChunk]:
    """Convert a PDF to DocumentChunks using docling's HybridChunker."""
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
