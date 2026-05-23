from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from harness_poc.core.document_index import DocumentIndexer
from harness_poc.core.skills import SkillResult
from harness_poc.core.vespa_client import LiveVespaDocumentClient

if TYPE_CHECKING:
    from harness_poc.core.skills import SkillContext


def execute(ctx: SkillContext, arguments: dict[str, Any]) -> SkillResult:
    if not ctx.config.retrieval.enabled:
        return SkillResult(
            status="failed",
            content="Retrieval is disabled. Set retrieval.enabled=true in harness.yaml.",
            artifacts={},
        )

    paths = arguments.get("paths")
    if not paths or not isinstance(paths, list):
        return SkillResult(
            status="failed",
            content="Missing required argument: paths (list of strings).",
            artifacts={},
        )

    glob_pattern = str(arguments.get("glob") or "**/*")
    force = bool(arguments.get("force", False))
    raw_exclude_dirs = arguments.get("exclude_dirs") or []
    if not isinstance(raw_exclude_dirs, list):
        return SkillResult(
            status="failed",
            content="exclude_dirs must be a list of directory paths.",
            artifacts={},
        )
    exclude_dirs = [str(path) for path in raw_exclude_dirs]

    vespa_client = LiveVespaDocumentClient(ctx.config.retrieval)
    indexer = DocumentIndexer(
        config=ctx.config.retrieval,
        database=ctx.database,
        vespa_client=vespa_client,
    )

    result = indexer.index_paths(
        project_root=ctx.project_root,
        paths=[str(path) for path in paths],
        glob_pattern=glob_pattern,
        exclude_dirs=exclude_dirs,
        force=force,
    )

    artifacts = {
        "indexed": result.indexed,
        "skipped": result.skipped,
        "failed": result.failed,
        "chunks_indexed": result.chunks_indexed,
        "failures": result.failures,
    }
    summary = (
        f"Indexed {result.indexed} source(s), {result.chunks_indexed} chunk(s). "
        f"Skipped {result.skipped}. Failed {result.failed}."
    )
    status = "failed" if result.failed > 0 and result.indexed == 0 else "success"
    failure_text = (
        "\n\nFailures:\n" + json.dumps(result.failures, indent=2) if result.failures else ""
    )

    return SkillResult(status=status, content=summary + failure_text, artifacts=artifacts)
