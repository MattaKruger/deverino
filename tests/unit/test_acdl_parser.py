"""Tests for the ACDL parser.

Covers: parsing real .acdl files, AST structure verification,
error reporting for malformed input, and round-trip validation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from harness_poc.core.acdl import ACDLFile, ParseError, parse, validate
from harness_poc.core.acdl.ast import (
    PromptDef,
    RoleFragDef,
    RoleMessage,
    StrFragDef,
)

# ---------------------------------------------------------------------------
# Real file tests
# ---------------------------------------------------------------------------

ACDL_FILES = [
    "deverino_react.acdl",
]


@pytest.mark.parametrize("path", ACDL_FILES)
def test_real_file_parses(path: str) -> None:
    """Every .acdl file in the repository must parse without errors."""
    source = Path(path).read_text()
    ast = parse(source, filename=path)
    assert isinstance(ast, ACDLFile)
    assert len(ast.blocks) > 0


def test_deverino_react_structure() -> None:
    """Verify the expected structure of deverino_react.acdl."""
    source = Path("deverino_react.acdl").read_text()
    ast = parse(source, filename="deverino_react.acdl")

    # Should have exactly 2 prompt definitions
    prompts = [b for b in ast.blocks if isinstance(b, PromptDef)]
    assert len(prompts) == 2
    assert {p.name for p in prompts} == {"DeverinoChatLoop", "DeverinoGoalLoop"}

    # Should have fragment definitions
    str_frags = [b for b in ast.blocks if isinstance(b, StrFragDef)]
    role_frags = [b for b in ast.blocks if isinstance(b, RoleFragDef)]
    assert len(str_frags) >= 9
    assert len(role_frags) >= 3

    # Verify specific fragments exist
    str_frag_names = {f.name for f in str_frags}
    assert "SoulCharter" in str_frag_names
    assert "StateBlock" in str_frag_names
    assert "ToolPolicyBlock" in str_frag_names
    assert "GoalHeader" in str_frag_names

    role_frag_names = {f.name for f in role_frags}
    assert "ConversationTurn" in role_frag_names
    assert "GoalEvaluationTurn" in role_frag_names
    assert "EventMappedTurn" in role_frag_names


def test_deverino_chat_loop_body() -> None:
    """Verify DeverinoChatLoop body contains expected role messages."""
    source = Path("deverino_react.acdl").read_text()
    ast = parse(source, filename="deverino_react.acdl")

    chat_loop = next(
        b for b in ast.blocks if isinstance(b, PromptDef) and b.name == "DeverinoChatLoop"
    )
    roles = [item for item in chat_loop.body if isinstance(item, RoleMessage)]
    role_values = {r.role for r in roles}
    assert "system" in role_values
    assert "user" in role_values


# ---------------------------------------------------------------------------
# Error handling tests
# ---------------------------------------------------------------------------


def test_unexpected_character() -> None:
    """A stray character should produce a ParseError with line/col info."""
    with pytest.raises(ParseError) as exc:
        parse("StrFrag X: { ~ }", filename="test.acdl")
    assert "test.acdl" in str(exc.value)
    assert "~" in str(exc.value)


def test_unclosed_brace() -> None:
    """Missing closing brace should produce a clear error."""
    with pytest.raises(ParseError):
        parse("StrFrag X: { sys.foo", filename="test.acdl")


def test_unclosed_block_in_prompt() -> None:
    """Missing closing brace in a prompt body should fail."""
    with pytest.raises(ParseError):
        parse("MyPrompt[@T]: { S: { Frag Foo ", filename="test.acdl")


def test_validate_returns_errors() -> None:
    """validate() should return error messages for invalid source."""
    errors = validate("StrFrag X: { ~ }", filename="test.acdl")
    assert len(errors) == 1
    assert "~" in errors[0]


def test_validate_returns_empty_for_valid() -> None:
    """validate() should return empty list for valid source."""
    source = 'StrFrag X: { "hello" }'
    errors = validate(source, filename="test.acdl")
    assert errors == []


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_empty_file() -> None:
    """An empty file should parse to zero blocks."""
    ast = parse("", filename="empty.acdl")
    assert len(ast.blocks) == 0


def test_comment_only_file() -> None:
    """A file with only comments should parse correctly."""
    ast = parse("// just a comment\n// another one", filename="comments.acdl")
    assert len(ast.blocks) == 2
    assert all(b.text for b in ast.blocks)  # type: ignore[attr-defined]


def test_str_frag_with_params() -> None:
    """StrFrag with parameters should parse correctly."""
    source = "StrFrag MyFrag[@t, $budget]: { sys.var }"
    ast = parse(source, filename="test.acdl")
    frag = ast.blocks[0]
    assert isinstance(frag, StrFragDef)
    assert frag.name == "MyFrag"
    assert frag.params == ["@t", "$budget"]
    assert len(frag.body) == 1


def test_role_frag_with_conditional() -> None:
    """RoleFrag with If/Else should parse correctly."""
    source = """
    RoleFrag Test[@t]: {
        If env.x != none {
            U: env.x
        }
        If env.y != none {
            A: { env.y }
        }
    }
    """
    ast = parse(source, filename="test.acdl")
    frag = ast.blocks[0]
    assert isinstance(frag, RoleFragDef)
    assert len(frag.body) >= 2


def test_prompt_with_namespace() -> None:
    """Prompt with Namespace block should parse correctly."""
    source = """
    MyPrompt[@T]: {
        Namespace env := {
            foo: string
            bar: string[]
        }
        S: { Frag X }
    }
    """
    ast = parse(source, filename="test.acdl")
    prompt = ast.blocks[0]
    assert isinstance(prompt, PromptDef)
    assert len(prompt.body) >= 2


# ---------------------------------------------------------------------------
# CI guard — validates every .acdl file in the repository
# ---------------------------------------------------------------------------


def test_all_acdl_files_in_repo_parse() -> None:
    """Every .acdl file in the repository must parse without errors."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    acdl_files = sorted(
        p
        for p in repo_root.glob("**/*.acdl")
        if ".deverino-scratch" not in str(p) and "node_modules" not in str(p)
    )
    assert acdl_files, "No .acdl files found — check glob pattern"

    failed: list[str] = []
    for path in acdl_files:
        try:
            rel = str(path.relative_to(repo_root))
            parse(path.read_text(), filename=rel)
        except ParseError as e:
            failed.append(str(e))

    if failed:
        pytest.fail("\n".join(failed))
