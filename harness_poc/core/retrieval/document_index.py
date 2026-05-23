from __future__ import annotations

import fnmatch
import hashlib
import logging
import re
import threading
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from harness_poc.core.retrieval.pdf_converter import convert_pdf_to_chunks
from harness_poc.core.retrieval.retrieval import make_document_chunks, make_source_id
from harness_poc.core.storage import DbDocumentChunk, DbDocumentSource

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from harness_poc.core.config import RetrievalConfig
    from harness_poc.core.retrieval.retrieval import VespaDocumentClient
    from harness_poc.core.storage import BlackboardAccessProxy, BlackboardDatabase

SUPPORTED_EXTENSIONS = frozenset(
    {".md", ".txt", ".rst", ".yaml", ".yml", ".json", ".toml", ".py", ".pdf"}
)

# Control characters (codepoints 0x00-0x1F) that are illegal in Vespa string fields,
# except for tab (0x09), newline (0x0A), and carriage return (0x0D).
_ILLEGAL_CONTROL_RE = re.compile(
    "[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]"
)
IGNORED_DIR_NAMES = frozenset({".git", ".venv", "__pycache__", ".deverino-scratch"})
IGNORED_FILE_GLOBS = frozenset({"*.db", ".env", "*.pem", "*.key", "id_rsa", "credentials.json"})


@dataclass
class IndexResult:
    indexed: int = 0
    skipped: int = 0
    failed: int = 0
    chunks_indexed: int = 0
    failures: list[dict[str, str]] = field(default_factory=list)


@dataclass
class _FileResult:
    """Per-file indexing outcome, safe to produce from worker threads."""

    uri: str
    status: str
    indexed: int = 0
    skipped: int = 0
    failed: int = 0
    chunks: int = 0
    failure: dict[str, str] | None = None


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
        self._print_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def changed_indexable_uris(
        self,
        project_root: Path,
        paths: list[str],
        glob_pattern: str = "**/*",
        *,
        exclude_dirs: list[str] | None = None,
    ) -> list[str]:
        """Return resolved URIs for indexable files that need feeding to Vespa."""
        resolved_root = project_root.resolve()
        resolved_files = self._resolve_files(
            resolved_root,
            paths,
            glob_pattern,
            exclude_dirs=exclude_dirs or [],
        )

        changed_uris: list[str] = []
        for file_path in resolved_files:
            try:
                uri = str(file_path.relative_to(resolved_root))
            except ValueError:
                changed_uris.append(str(file_path))
                continue

            if not _is_indexable_file(file_path):
                continue

            try:
                content_hash = _compute_file_hash(file_path)
            except OSError:
                changed_uris.append(uri)
                continue

            existing = self._db.get_document_source(make_source_id(uri))
            if existing is None:
                changed_uris.append(uri)
                continue
            if existing.content_hash != content_hash:
                changed_uris.append(uri)
                continue
            if existing.status not in {"indexed", "skipped"}:
                changed_uris.append(uri)

        return changed_uris

    def has_indexable_changes(
        self,
        project_root: Path,
        paths: list[str],
        glob_pattern: str = "**/*",
        *,
        exclude_dirs: list[str] | None = None,
    ) -> bool:
        """Return True when any resolved indexable file needs feeding to Vespa."""
        return bool(
            self.changed_indexable_uris(
                project_root=project_root,
                paths=paths,
                glob_pattern=glob_pattern,
                exclude_dirs=exclude_dirs,
            )
        )

    def index_paths(
        self,
        project_root: Path,
        paths: list[str],
        glob_pattern: str = "**/*",
        *,
        exclude_dirs: list[str] | None = None,
        force: bool = False,
    ) -> IndexResult:
        result = IndexResult()
        resolved_root = project_root.resolve()

        logger.info(
            "Starting document indexing: paths=%s glob=%s force=%s",
            paths,
            glob_pattern,
            force,
        )

        try:
            self._vespa.health_check()
        except Exception as exc:
            logger.exception("Vespa health check failed")
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

        resolved_files = self._resolve_files(
            resolved_root,
            paths,
            glob_pattern,
            exclude_dirs=exclude_dirs or [],
        )
        total = len(resolved_files)
        if total == 0:
            logger.info("No files resolved for indexing")
            return result

        logger.info("Resolved %d file(s) to process", total)

        max_workers = max(1, self._config.max_feed_workers)
        with self._print_lock:
            print(f"\nIndexing {total} file(s) with {max_workers} worker(s)...\n")

        # Build (uri, file_path) pairs, rejecting paths outside project root upfront.
        work_items: list[tuple[str, Path]] = []
        for file_path in resolved_files:
            try:
                uri = str(file_path.relative_to(resolved_root))
            except ValueError:
                result.failed += 1
                result.failures.append(
                    {"uri": str(file_path), "error": "path outside project root"}
                )
                continue
            work_items.append((uri, file_path))

        # Process files in parallel.
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_map: dict[Future[_FileResult], tuple[int, str]] = {}
            for idx, (uri, file_path) in enumerate(work_items, start=1):
                future = executor.submit(
                    self._index_one_isolated,
                    file_path,
                    uri,
                    force=force,
                )
                future_map[future] = (idx, uri)

            for future in as_completed(future_map):
                idx, uri = future_map[future]
                try:
                    file_result = future.result()
                except Exception as exc:
                    logger.exception("Worker failed for %s", uri)
                    file_result = _FileResult(
                        uri=uri,
                        status="failed",
                        failed=1,
                        failure={"uri": uri, "error": str(exc)},
                    )

                # Merge into shared result.
                result.indexed += file_result.indexed
                result.skipped += file_result.skipped
                result.failed += file_result.failed
                result.chunks_indexed += file_result.chunks
                if file_result.failure is not None:
                    result.failures.append(file_result.failure)

                logger.info(
                    "[%d/%d] %s %s",
                    idx,
                    total,
                    file_result.status,
                    uri,
                )
                with self._print_lock:
                    detail = ""
                    if file_result.failure:
                        detail = f" — {file_result.failure['error']}"
                    print(f"  [{idx}/{total}] {file_result.status} {uri}{detail}")

        return result

    # ------------------------------------------------------------------
    # Per-file indexing (thread-safe — only touches its own file's data)
    # ------------------------------------------------------------------

    def _index_one_isolated(  # noqa: PLR0911
        self,
        file_path: Path,
        uri: str,
        *,
        force: bool,
    ) -> _FileResult:
        """Index a single file and return its outcome without mutating shared state."""
        source_id = make_source_id(uri)

        if not _is_indexable_file(file_path):
            return _FileResult(uri=uri, status="skipped", skipped=1)

        title = file_path.stem.replace("-", " ").replace("_", " ").title()

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
            content_hash = _compute_file_hash(file_path)
        except OSError as exc:
            return _FileResult(
                uri=uri,
                status="failed",
                failed=1,
                failure={"uri": uri, "error": str(exc)},
            )

        existing = self._db.get_document_source(source_id)
        if (
            existing is not None
            and existing.content_hash == content_hash
            and existing.status in {"indexed", "skipped"}
            and not force
        ):
            self._db.upsert_document_source(
                _make_db_source(
                    source_id=source_id,
                    uri=uri,
                    content_hash=content_hash,
                    status="indexed",
                    chunk_count=existing.chunk_count,
                    title=existing.title,
                    indexed_at=existing.indexed_at,
                )
            )
            return _FileResult(uri=uri, status="skipped", skipped=1)

        if file_path.suffix.lower() == ".pdf":
            try:
                chunks = convert_pdf_to_chunks(
                    file_path=file_path,
                    uri=uri,
                    title=title,
                    kind=_infer_kind(uri),
                    max_tokens=self._config.chunk_size_chars,
                )
            except Exception as exc:  # noqa: BLE001
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
        else:
            try:
                text = _sanitize_text(_read_document_text(file_path))
            except (OSError, UnicodeError) as exc:
                return _FileResult(
                    uri=uri,
                    status="failed",
                    failed=1,
                    failure={"uri": uri, "error": str(exc)},
                )
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

    # ------------------------------------------------------------------
    # File resolution
    # ------------------------------------------------------------------

    def _resolve_files(
        self,
        project_root: Path,
        paths: list[str],
        glob_pattern: str,
        *,
        exclude_dirs: list[str],
    ) -> list[Path]:
        ignore_prefixes = _resolve_ignore_prefixes(
            project_root, [*self._config.auto_index_ignore_paths, *exclude_dirs]
        )
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
            if _under_ignore_prefix(path, ignore_prefixes):
                continue
            if path.is_file():
                files.append(path)
            elif path.is_dir():
                for child in path.rglob(glob_pattern):
                    resolved_child = child.resolve()
                    if not resolved_child.is_file():
                        continue
                    if _in_ignored_dir(resolved_child, project_root):
                        continue
                    if _under_ignore_prefix(resolved_child, ignore_prefixes):
                        continue
                    files.append(resolved_child)
        return files


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------


def _in_ignored_dir(path: Path, project_root: Path) -> bool:
    try:
        rel = path.relative_to(project_root)
    except ValueError:
        return False
    return any(part in IGNORED_DIR_NAMES for part in rel.parts)


def _resolve_ignore_prefixes(project_root: Path, raw_paths: list[str]) -> list[Path]:
    """Resolve user-supplied ignore paths (relative or absolute) against project_root."""
    resolved: list[Path] = []
    for raw in raw_paths:
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = project_root / candidate
        resolved.append(candidate.resolve())
    return resolved


def _under_ignore_prefix(path: Path, ignore_prefixes: list[Path]) -> bool:
    for prefix in ignore_prefixes:
        if path == prefix:
            return True
        try:
            path.relative_to(prefix)
        except ValueError:
            continue
        return True
    return False


def _is_secret_file(name: str) -> bool:
    return any(fnmatch.fnmatch(name, pattern) for pattern in IGNORED_FILE_GLOBS)


def _is_indexable_file(file_path: Path) -> bool:
    return file_path.suffix.lower() in SUPPORTED_EXTENSIONS and not _is_secret_file(
        file_path.name
    )


def _read_document_text(file_path: Path) -> str:
    return file_path.read_text(encoding="utf-8", errors="replace")


def _compute_file_hash(file_path: Path) -> str:
    return hashlib.sha256(file_path.read_bytes()).hexdigest()


def _sanitize_text(text: str) -> str:
    """Strip control characters that are illegal in Vespa string fields."""
    return _ILLEGAL_CONTROL_RE.sub(" ", text)


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
