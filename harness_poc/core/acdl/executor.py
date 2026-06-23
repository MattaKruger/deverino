"""ACDL executor — drives system-prompt composition from a parsed .acdl spec.

The "flip the arrow": the runtime used to hand-assemble the system prompt in
``app_factory._system_message_for``. Now the *composition* (fragment order,
literal headers, the context-map conditional) lives in ``deverino_react.acdl``
and this module interprets it. Python still *computes the values* (soul, state,
context-map render) and passes them in as ``bindings``.

Scope is deliberately small — only the constructs the chat loop's ``S:`` block
actually uses: StrFrag bodies, ``Frag`` invocations, ``If <var> != none`` /
``== none`` conditionals, string literals, ``sys.*`` references.

ponytail: prompt composition only. The turn loop (RoleFrag/ForEach/ACTION_RECORD)
stays in pydantic-ai — re-running it from ACDL would rebuild the agent for nothing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from harness_poc.core.acdl.ast import (
    Comparison,
    ConditionalBlock,
    ContextVar,
    FragInvocation,
    Identifier,
    StringLiteral,
)

if TYPE_CHECKING:
    from harness_poc.core.acdl.ast import ACDLFile, Expression


def assemble_system_prompt(
    spec: ACDLFile,
    bindings: dict[str, str],
    *,
    prompt_name: str = "DeverinoChatLoop",
) -> str:
    """Assemble the system prompt from the spec's ``S:`` block.

    ``bindings`` maps namespaced variables (``"sys.soul_charter"``) to their
    runtime text. A fragment is included iff it references at least one bound
    variable and *every* variable it references is bound — so fragments owned
    by other seams (literal tool-policy, the unbound skill catalog) are skipped
    here without a hand-maintained skip list.
    """
    prompt = spec.prompt_named(prompt_name)
    if prompt is None:
        msg = f"ACDL spec has no prompt named {prompt_name!r}"
        raise ValueError(msg)
    system_block = next((m for m in prompt.role_messages() if m.role == "system"), None)
    if system_block is None:
        msg = f"Prompt {prompt_name!r} has no system (S:) block"
        raise ValueError(msg)

    blocks = _render_items(system_block.body, spec, bindings)
    return "\n\n".join(b for b in blocks if b)


def _render_items(items: list, spec: ACDLFile, bindings: dict[str, str]) -> list[str]:
    blocks: list[str] = []
    for item in items:
        if isinstance(item, FragInvocation):
            rendered = _render_frag(item.name, spec, bindings)
            if rendered is not None:
                blocks.append(rendered)
        elif isinstance(item, ConditionalBlock):
            blocks.extend(_render_conditional(item, spec, bindings))
        elif isinstance(item, StringLiteral):
            blocks.append(item.value)
    return blocks


def _render_conditional(
    block: ConditionalBlock, spec: ACDLFile, bindings: dict[str, str]
) -> list[str]:
    if block.if_condition is not None and _cond_true(block.if_condition, bindings):
        return _render_items(block.if_body, spec, bindings)
    for cond, body in zip(block.else_if_conditions, block.else_if_bodies, strict=False):
        if _cond_true(cond, bindings):
            return _render_items(body, spec, bindings)
    if block.else_body is not None:
        return _render_items(block.else_body, spec, bindings)
    return []


def _render_frag(name: str, spec: ACDLFile, bindings: dict[str, str]) -> str | None:
    """Render a StrFrag body to text, or None if this seam doesn't own it.

    Returns None when the frag has no bound variables (literal-only, owned
    elsewhere) or references a variable absent from ``bindings``.
    """
    frag = spec.fragment_named(name)
    if frag is None or not _is_str_frag(frag):
        return None

    lines: list[str] = []
    saw_bound_var = False
    for item in frag.body:
        if isinstance(item, StringLiteral):
            lines.append(item.value)
        elif isinstance(item, ContextVar):
            key = _var_key(item)
            if key not in bindings:
                return None  # owned by another seam
            saw_bound_var = True
            lines.append(bindings[key])
        elif isinstance(item, ConditionalBlock):
            lines.extend(_render_items(item.if_body, spec, bindings))
        # CommentBlock / NameDef / nested frags: skip for the chat S block

    if not saw_bound_var:
        return None  # purely literal fragment — not this seam's job
    return "\n".join(lines)


def _cond_true(expr: Expression, bindings: dict[str, str]) -> bool:
    """Evaluate the only condition shape the spec uses: ``<var> != none``."""
    if isinstance(expr, Comparison) and isinstance(expr.right, Identifier):
        present = bool(bindings.get(_var_key(expr.left)))
        if expr.right.name == "none":
            return present if expr.operator == "!=" else not present
    return True  # unknown condition — lenient (include)


def _var_key(expr: Expression) -> str:
    if isinstance(expr, ContextVar):
        return ".".join([expr.namespace, *expr.path])
    return ""


def _is_str_frag(frag: object) -> bool:
    # Avoid importing StrFragDef at runtime just for an isinstance; body shape suffices.
    return hasattr(frag, "body") and not hasattr(frag, "indices")


