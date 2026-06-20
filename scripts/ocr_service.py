#!/usr/bin/env python3
"""Standalone OCR service that keeps docling models warm between requests.

The service initializes docling's DocumentConverter (RapidOCR + torch)
and HybridChunker once at startup, then reuses them for every conversion
request, avoiding the ~5-10s per-file cold-start overhead.

Usage:
    uv run python scripts/ocr_service.py
    uv run python scripts/ocr_service.py --port 8001
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logger = logging.getLogger("ocr_service")


# ── Globals: initialized once at startup ──────────────────────────────
_converter: object | None = None
_chunker: object | None = None
_tokenizer: object | None = None
_current_max_tokens: int = 0


def _init_docling(max_chunk_tokens: int) -> None:
    """Load docling converter + chunker once and cache globally."""
    global _converter, _chunker, _tokenizer, _current_max_tokens  # noqa: PLW0603

    # fmt: off
    # docling imports are intentionally lazy to avoid loading torch at module level
    from docling.chunking import HybridChunker  # noqa: I001, PLC0415
    from docling.datamodel.base_models import InputFormat  # noqa: PLC0415
    from docling.datamodel.pipeline_options import (  # noqa: PLC0415
        AcceleratorDevice,
        AcceleratorOptions,
        PdfPipelineOptions,
    )
    from docling.document_converter import DocumentConverter, PdfFormatOption  # noqa: PLC0415
    from docling_core.transforms.chunker.hybrid_chunker import get_default_tokenizer  # noqa: PLC0415
    from docling_core.transforms.chunker.tokenizer.huggingface import HuggingFaceTokenizer  # noqa: PLC0415
    # fmt: on

    logger.info("Initializing docling DocumentConverter (RapidOCR + torch)...")
    pipeline_options = PdfPipelineOptions()
    pipeline_options.accelerator_options = AcceleratorOptions(device=AcceleratorDevice.CPU)
    pipeline_options.do_ocr = False
    pipeline_options.do_table_structure = False
    pipeline_options.force_backend_text = True  # use PDF embedded text (fast); skip ML layout
    _converter = DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)}
    )

    logger.info("Initializing HybridChunker + HuggingFace tokenizer...")
    default_tokenizer = get_default_tokenizer()
    _tokenizer = HuggingFaceTokenizer(
        tokenizer=default_tokenizer.tokenizer, max_tokens=max_chunk_tokens
    )
    _chunker = HybridChunker(tokenizer=_tokenizer)
    _current_max_tokens = max_chunk_tokens

    logger.info("OCR service ready.")


def _ensure_tokenizer(max_tokens: int) -> None:
    """Re-init chunker if max_tokens changed (cheap, only swaps tokenizer wrapper)."""
    global _chunker, _tokenizer, _current_max_tokens  # noqa: PLW0603
    if max_tokens == _current_max_tokens:
        return
    from docling.chunking import HybridChunker  # noqa: I001, PLC0415
    from docling_core.transforms.chunker.hybrid_chunker import get_default_tokenizer  # noqa: PLC0415
    from docling_core.transforms.chunker.tokenizer.huggingface import HuggingFaceTokenizer  # noqa: PLC0415

    default_tokenizer = get_default_tokenizer()
    _tokenizer = HuggingFaceTokenizer(tokenizer=default_tokenizer.tokenizer, max_tokens=max_tokens)
    _chunker = HybridChunker(tokenizer=_tokenizer)
    _current_max_tokens = max_tokens


@asynccontextmanager
async def lifespan(app: FastAPI) -> object:
    _init_docling(app.state.max_chunk_tokens)
    yield


# ── Pydantic models ───────────────────────────────────────────────────


class ConvertRequest(BaseModel):
    file_path: str
    uri: str
    title: str
    kind: str
    max_tokens: int = 1800


class ChunkData(BaseModel):
    source_id: str
    uri: str
    title: str
    chunk_id: str
    chunk_index: int
    text: str
    kind: str
    content_hash: str
    updated_at: int


# ── FastAPI app ───────────────────────────────────────────────────────

app = FastAPI(title="Deverino OCR Service", lifespan=lifespan)


def _make_source_id(uri: str) -> str:
    """Derive a stable source_id slug from a relative URI."""
    slug = uri.replace("/", "-").replace("\\", "-").replace(".", "-").strip("-")
    return slug.lower()


def _make_chunk_id(source_id: str, chunk_index: int) -> str:
    return f"{source_id}-{chunk_index:05d}"


def _compute_content_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _extract_chunk_title(chunk: object) -> str:
    """Return the most specific heading from chunk metadata, or empty string."""
    meta = getattr(chunk, "meta", None)
    headings = getattr(meta, "headings", None)
    if isinstance(headings, list) and headings:
        return str(headings[-1])
    return ""


@app.post("/convert", response_model=list[ChunkData])
def convert_pdf(req: ConvertRequest) -> list[ChunkData]:
    """Convert a PDF to document chunks using the pre-warmed docling converter."""
    file_path = Path(req.file_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {req.file_path}")
    if not file_path.is_file():
        raise HTTPException(status_code=400, detail=f"Not a file: {req.file_path}")

    _ensure_tokenizer(req.max_tokens)

    logger.info("Converting %s", file_path.name)
    result = _converter.convert(file_path)  # type: ignore[union-attr]
    doc = result.document

    source_id = _make_source_id(req.uri)
    now_ms = int(time.time() * 1000)
    chunks: list[ChunkData] = []

    out_index = 0
    for chunk in _chunker.chunk(doc):  # type: ignore[union-attr]
        chunk_title = _extract_chunk_title(chunk) or req.title
        text = chunk.text or ""
        if not text.strip():
            continue
        chunks.append(
            ChunkData(
                source_id=source_id,
                uri=req.uri,
                title=chunk_title,
                chunk_id=_make_chunk_id(source_id, out_index),
                chunk_index=out_index,
                text=text,
                kind=req.kind,
                content_hash=_compute_content_hash(text),
                updated_at=now_ms,
            )
        )
        out_index += 1

    logger.info("Converted %s -> %d chunks", file_path.name, len(chunks))
    return chunks


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# ── CLI entrypoint ────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Deverino OCR Service")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8001, help="Port (default: 8001)")
    parser.add_argument(
        "--max-chunk-tokens",
        type=int,
        default=1800,
        help="Default chunk token limit (default: 1800)",
    )
    args = parser.parse_args()

    app.state.max_chunk_tokens = args.max_chunk_tokens

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    logger.info("Starting OCR service on %s:%d", args.host, args.port)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
