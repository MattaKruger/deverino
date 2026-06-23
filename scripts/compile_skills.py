# ruff: noqa: E402, INP001, S603, S607, SLF001
"""Recompile all project skills using `codex exec` as the LLM backend."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

import harness_poc.core.skills.skill_compiler as _compiler
from harness_poc.core.config import HarnessConfig
from harness_poc.core.skills.skill_compiler import (
    _STAGE3_SYSTEM_PROMPT,
    LlmContractOutput,
    _extract_contracts,
    _llm_output_to_dataclasses,
    _parse_llm_json,
    compile_skill,
)
from harness_poc.core.skills.skill_runner import SkillRunner

if TYPE_CHECKING:
    from harness_poc.core.config import CompilerConfig
    from harness_poc.core.skills.skill_bundle import ActionTemplate, InvokePattern, TypedContract
    from harness_poc.core.skills.skill_compiler import ProceduralUnit, UnitCluster
    from harness_poc.core.skills.skill_runner import SkillDocument


class _ParserOnlySkillRunner:
    def __init__(self, skills_dirs: tuple[Path, Path]) -> None:
        self.skills_dirs = skills_dirs

    @staticmethod
    def parse_skill_document(skill_file: Path) -> SkillDocument:
        return SkillRunner.parse_skill_document(skill_file)


def _codex_cli_extract(
    clusters: list[UnitCluster],
    units: list[ProceduralUnit],
    doc: SkillDocument,
    model: object,  # noqa: ARG001
    compiler_config: CompilerConfig,  # noqa: ARG001
) -> tuple[list[TypedContract], dict[str, ActionTemplate], list[InvokePattern]]:
    """Drop-in for _extract_contracts_llm that calls `codex exec` instead of pydantic_ai."""
    metadata = doc["metadata"]
    frontmatter_params = metadata.get("parameters", {}).get("properties", {})

    contracts, templates, invoke_patterns = [], {}, []
    cluster_text = "\n\n".join(
        f"## Cluster {idx}\n"
        + "\n\n---\n\n".join(f"[Unit {i}]\n{t}" for i, t in enumerate(cluster.texts))
        for idx, cluster in enumerate(clusters)
    )
    user_prompt = (
        'Return only JSON. Return a top-level object shaped as {"items": [...]}, '
        "where each item matches the compiler schema below. Omit clusters that have no "
        "extractable contract.\n\n"
        f"{_STAGE3_SYSTEM_PROMPT}\n\n"
        f"Skill: {metadata['name']}\n"
        f"Frontmatter parameters: {json.dumps(frontmatter_params)}\n\n"
        f"Procedural clusters:\n\n{cluster_text}"
    )

    try:
        with tempfile.NamedTemporaryFile("r+", suffix=".json", delete=True) as output_file:
            result = subprocess.run(
                [
                    "codex",
                    "-a",
                    "never",
                    "exec",
                    "--ephemeral",
                    "--sandbox",
                    "read-only",
                    "-C",
                    str(REPO_ROOT),
                    "-o",
                    output_file.name,
                    user_prompt,
                ],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=240,
                check=False,
            )
            output_file.seek(0)
            raw = output_file.read().strip()
        if result.returncode != 0 or not raw:
            detail = (result.stderr or result.stdout)[:200]
            print(f"    codex exec failed for {metadata['name']}: {detail} — falling back to stub")
            return _extract_contracts(clusters, units)
    except Exception as exc:
        print(f"    codex exec failed for {metadata['name']}: {exc} — falling back to stub")
        return _extract_contracts(clusters, units)

    outputs = _parse_codex_outputs(raw)
    if not outputs:
        print(f"    unparseable codex output for {metadata['name']}, falling back to stub")
        return _extract_contracts(clusters, units)

    for idx, output in enumerate(outputs):
        contract, tmpl, inv = _llm_output_to_dataclasses(output)
        if contract is not None:
            contracts.append(contract)
        if tmpl is not None:
            templates[contract.name if contract else f"cluster_{idx}"] = tmpl
        if inv is not None:
            invoke_patterns.append(inv)

    return contracts, templates, invoke_patterns


def _parse_codex_outputs(raw: str) -> list[LlmContractOutput]:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:] if len(lines) > 1 else lines
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        obj, _ = json.JSONDecoder().raw_decode(text)
        items = obj.get("items", []) if isinstance(obj, dict) else obj
        if not isinstance(items, list):
            return []
        return [LlmContractOutput.model_validate(item) for item in items]
    except Exception:
        single = _parse_llm_json(raw)
        return [single] if single is not None else []


# Patch before any compile_skill calls
cast("Any", _compiler)._extract_contracts_llm = _codex_cli_extract

config = HarnessConfig.load()
skill_dirs = (config.paths.system_skills, config.paths.project_skills)
skill_runner = cast("SkillRunner", _ParserOnlySkillRunner(skill_dirs))

skill_files = [
    sf
    for d in skill_dirs
    if d.exists()
    for sf in sorted(d.glob("*/SKILL.md"))
]

print(f"Compiling {len(skill_files)} skills via `codex exec`...\n")

ok = err = 0
for sf in skill_files:
    try:
        # sentinel object — non-None triggers LLM path; patched fn ignores it
        bundle = compile_skill(
            sf,
            skill_runner=skill_runner,
            force=True,
            model=object(),  # type: ignore[arg-type]
            compiler_config=config.compiler,
        )
        status = bundle.compilation_status
        nerr = len(bundle.compilation_errors)
        marker = "✓" if status == "full" else ("~" if status == "partial" else "✗")
        print(f"  {marker} {sf.parent.name} [{status}]" + (f" ({nerr} errors)" if nerr else ""))
        ok += 1
    except Exception as e:
        print(f"  ✗ {sf.parent.name} EXCEPTION: {e}")
        err += 1

print(f"\nDone: {ok} compiled, {err} exceptions")
