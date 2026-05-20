from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from harness_poc.core.models import DbDocumentChunk, DbDocumentSource
from harness_poc.core.retrieval import compute_content_hash, make_document_chunks, make_source_id

if TYPE_CHECKING:
    from harness_poc.core.blackboard_proxy import BlackboardAccessProxy
    from harness_poc.core.config import RetrievalConfig
    from harness_poc.core.database import BlackboardDatabase
    from harness_poc.core.retrieval import VespaDocumentClient

SUPPORTED_EXTENSIONS = frozenset(
    {".md", ".txt", ".rst", ".yaml", ".yml", ".json", ".toml", ".py", ".pdf"}
)
IGNORED_DIR_NAMES = frozenset({".git", ".venv", "__pycache__", ".deverino-scratch"})
IGNORED_FILE_GLOBS = frozenset({"*.db", ".env", "*.pem", "*.key", "id_rsa", "credentials.json"})
MAX_FILE_BYTES = 5 * 1024 * 1024


@dataclass
class IndexResult:
    indexed: int = 0
    skipped: int = 0
    failed: int = 0
    chunks_indexed: int = 0
    failures: list[dict[str, str]] = field(default_factory=list)


class DocumentIndexer:
    def __init__(
        self,
        config: RetrievalConfig,
        database: BlackboardDatabase | BlackboardAccessProxy,
        vespa_client: VespaDocumentClient,
    ) -> None:
        self._config = config
        self._db = database
        self._vespa = vespa_client

    def index_paths(
        self,
        project_root: Path,
        paths: list[str],
        glob_pattern: str = "**/*",
        *,
        force: bool = False,
    ) -> IndexResult:
        result = IndexResult()
        resolved_root = project_root.resolve()

        try:
            self._vespa.health_check()
        except Exception as exc:  # noqa: BLE001
            for raw_path in paths:
                uri = raw_path
                source_id = make_source_id(uri)
                self._db.upsert_document_source(
                    DbDocumentSource(
                        source_id=source_id,
                        uri=uri,
                        title=uri,
                        kind=_infer_kind(uri),
                        content_hash="",
                        status="failed",
                        chunk_count=0,
                        indexed_at=None,
                        error=str(exc),
                        metadata_payload={},
                        updated_at=_utc_now(),
                    )
                )
                result.failed += 1
                result.failures.append({"uri": uri, "error": str(exc)})
            return result

        for file_path in self._resolve_files(resolved_root, paths, glob_pattern):
            try:
                uri = str(file_path.relative_to(resolved_root))
            except ValueError:
                result.failed += 1
                result.failures.append(
                    {"uri": str(file_path), "error": "path outside project root"}
                )
                continue

            self._index_one(file_path, uri, force=force, result=result)

        return result

    def _index_one(
        self,
        file_path: Path,
        uri: str,
        *,
        force: bool,
        result: IndexResult,
    ) -> None:
        source_id = make_source_id(uri)

        if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            result.skipped += 1
            return

        if _is_secret_file(file_path.name):
            result.skipped += 1
            return

        try:
            if file_path.stat().st_size > MAX_FILE_BYTES:
                result.failed += 1
                result.failures.append(
                    {"uri": uri, "error": f"file exceeds {MAX_FILE_BYTES} bytes"}
                )
                return
            text = _read_document_text(file_path)
        except (OSError, PdfReadError, UnicodeError) as exc:
            result.failed += 1
            result.failures.append({"uri": uri, "error": str(exc)})
            return

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
            result.skipped += 1
            return

        title = file_path.stem.replace("-", " ").replace("_", " ").title()
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
            result.failed += 1
            result.failures.append({"uri": uri, "error": error_msg})
            return

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
        result.indexed += 1
        result.chunks_indexed += len(chunks)

    def _resolve_files(self, project_root: Path, paths: list[str], glob_pattern: str) -> list[Path]:
        files: list[Path] = []
        for raw_path in paths:
            path = Path(raw_path)
            if not path.is_absolute():
                path = project_root / path
            path = path.resolve()

            try:
                path.relative_to(project_root)
            except ValueError:
                files.append(path)
                continue

            if _in_ignored_dir(path, project_root):
                continue
            if path.is_file():
                files.append(path)
            elif path.is_dir():
                for child in path.rglob(glob_pattern):
                    resolved_child = child.resolve()
                    if resolved_child.is_file() and not _in_ignored_dir(
                        resolved_child, project_root
                    ):
                        files.append(resolved_child)
        return files


def _in_ignored_dir(path: Path, project_root: Path) -> bool:
    try:
        rel = path.relative_to(project_root)
    except ValueError:
        return False
    return any(part in IGNORED_DIR_NAMES for part in rel.parts)


def _is_secret_file(name: str) -> bool:
    return any(fnmatch.fnmatch(name, pattern) for pattern in IGNORED_FILE_GLOBS)


def _read_document_text(file_path: Path) -> str:
    if file_path.suffix.lower() == ".pdf":
        return _read_pdf_text(file_path)
    return file_path.read_text(encoding="utf-8", errors="replace")


def _read_pdf_text(file_path: Path) -> str:
    page_texts: list[str] = []
    with file_path.open("rb") as pdf_file:
        reader = PdfReader(pdf_file)
        for page_number, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            if text.strip():
                page_texts.append(f"[Page {page_number}]\n{text.strip()}")
    return "\n\n".join(page_texts)


def _infer_kind(uri: str) -> str:
    if uri.startswith("docs/superpowers/specs/"):
        return "spec"
    if uri.startswith("docs/superpowers/plans/"):
        return "plan"
    if uri.startswith("docs/"):
        return "doc"
    return "source"


def _make_db_source(  # noqa: PLR0913
    source_id: str,
    uri: str,
    content_hash: str,
    status: str,
    chunk_count: int,
    title: str = "",
    indexed_at: str | None = None,
    error: str | None = None,
) -> DbDocumentSource:
    return DbDocumentSource(
        source_id=source_id,
        uri=uri,
        title=title or uri,
        kind=_infer_kind(uri),
        content_hash=content_hash,
        status=status,
        chunk_count=chunk_count,
        indexed_at=indexed_at,
        error=error,
        metadata_payload={},
        updated_at=_utc_now(),
    )


def _utc_now() -> str:
    return datetime.now(tz=UTC).isoformat(timespec="seconds")
