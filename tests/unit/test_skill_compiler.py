from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from harness_poc.core.skills.skill_bundle import ActionTemplate, JsonSchemaProperty, TypedContract
from harness_poc.core.skills.skill_compiler import (
    _compile_from_doc,
    _llm_output_to_dataclasses,
    _parse_llm_json,
    _verify_contracts,
)
from harness_poc.core.skills.skill_runner import SkillDocument, SkillMetadata


def _metadata(
    *,
    skill_type: str = "tool",
    properties: dict[str, Any] | None = None,
) -> SkillMetadata:
    return {
        "name": "demo_skill",
        "description": "Demo skill.",
        "type": skill_type,
        "parameters": {"type": "object", "properties": properties or {}},
        "auto_invokable": False,
        "permissions": {},
        "version": "1.0",
        "aliases": [],
    }


def test_parse_llm_json_accepts_fenced_json_with_trailing_text() -> None:
    raw = """```json
{
  "contract": {
    "name": "run_compile",
    "description": "Compile skills",
    "inputs": {"skill_path": {"type": "string", "description": "Path"}},
    "outputs": {},
    "side_effects": [],
    "preconditions": [],
    "postconditions": [],
    "error_conditions": [],
    "cancellation_behavior": "definitely"
  },
  "action_template": {
    "kind": "cli",
    "template": "claude -p {skill_path}",
    "argument_map": {"skill_path": "skill_path"}
  },
  "invoke_pattern": {
    "arguments": {"skill_path": "skills/demo/SKILL.md"},
    "rendered_call": "claude -p skills/demo/SKILL.md"
  }
}
```
Parsed successfully.
"""

    output = _parse_llm_json(raw)

    assert output is not None
    contract, template, invoke = _llm_output_to_dataclasses(output)
    assert contract is not None
    assert contract.cancellation_behavior == "unknown"
    assert template is not None
    assert template.kind == "shell"
    assert invoke is not None
    assert invoke.contract_name == "run_compile"


def test_llm_output_drops_unknown_action_template_kind() -> None:
    raw = """{
  "contract": {
    "name": "run_compile",
    "description": "Compile skills",
    "inputs": {},
    "outputs": {},
    "side_effects": [],
    "preconditions": [],
    "postconditions": [],
    "error_conditions": [],
    "cancellation_behavior": "safe"
  },
  "action_template": {
    "kind": "spreadsheet",
    "template": "not a supported action kind",
    "argument_map": {}
  },
  "invoke_pattern": {
    "arguments": {},
    "rendered_call": "not a supported action kind"
  }
}"""

    output = _parse_llm_json(raw)

    assert output is not None
    _contract, template, invoke = _llm_output_to_dataclasses(output)
    assert template is None
    assert invoke is not None


def test_compile_flat_body_without_units_is_full_raw_body_fallback() -> None:
    doc = cast(
        "SkillDocument",
        {
            "metadata": _metadata(),
            "body": "Use this as reference prose without headings, steps, or code.",
            "path": Path("skills/demo/SKILL.md"),
            "entrypoint": {"module": "skill", "function": "execute"},
        },
    )

    bundle = _compile_from_doc(doc)

    assert bundle.compilation_status == "full"
    assert bundle.compilation_errors == []
    assert bundle.contracts == {}
    assert bundle.parent_skeleton == doc["body"]


def test_verify_contracts_skips_frontmatter_binding_for_knowledge_skills() -> None:
    contract = TypedContract(
        name="explain_reference",
        description="Explain a reference topic.",
        inputs={"topic": JsonSchemaProperty({"type": "string"})},
    )

    promoted, errors = _verify_contracts(
        [contract],
        {},
        "Explain the reference material.",
        _metadata(skill_type="knowledge", properties={}),
    )

    assert promoted == [contract]
    assert errors == []


def test_verify_contracts_allows_frontmatter_params_as_risk_tokens() -> None:
    contract = TypedContract(
        name="search_documents",
        description="Search documents.",
        inputs={"query": JsonSchemaProperty({"type": "string"})},
    )
    template = ActionTemplate(
        kind="shell",
        template="semble search {query}",
        argument_map={"query": "query"},
    )

    promoted, errors = _verify_contracts(
        [contract],
        {"search_documents": template},
        "Run `semble search` against the indexed documents.",
        _metadata(properties={"query": {"type": "string"}}),
    )

    assert promoted == [contract]
    assert errors == []
