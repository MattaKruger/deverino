"""AST node definitions for the ACDL parser.

Mirrors the structure produced by the JS renderer's parser closely enough
that the JS AST can serve as a reference. All nodes are frozen dataclasses.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Tokens (also used as opaque expression carriers)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Token:
    """A lexical token produced by the scanner."""

    type: str  # "COMMENT" | "STRING" | "IDENT" | "KEYWORD" | "SYMBOL" | "NUMBER" | "EOF"
    value: str
    line: int
    col: int


# ---------------------------------------------------------------------------
# Top-level container
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ACDLFile:
    """Root AST node. Contains all top-level blocks in file order."""

    blocks: list[Block]

    # -- query API -----------------------------------------------------------

    def str_frags(self) -> list[StrFragDef]:
        """All StrFrag definitions in file order."""
        return [b for b in self.blocks if isinstance(b, StrFragDef)]

    def role_frags(self) -> list[RoleFragDef]:
        """All RoleFrag definitions in file order."""
        return [b for b in self.blocks if isinstance(b, RoleFragDef)]

    def fragments(self) -> list[StrFragDef | RoleFragDef]:
        """All fragment definitions (StrFrag + RoleFrag) in file order."""
        return [b for b in self.blocks if isinstance(b, (StrFragDef, RoleFragDef))]

    def fragment_named(self, name: str) -> StrFragDef | RoleFragDef | None:
        """Find a fragment by name. Returns None if not found."""
        for f in self.fragments():
            if f.name == name:
                return f
        return None

    def prompts(self) -> list[PromptDef]:
        """All prompt/chart definitions in file order."""
        return [b for b in self.blocks if isinstance(b, PromptDef)]

    def prompt_named(self, name: str) -> PromptDef | None:
        """Find a prompt by name. Returns None if not found."""
        for p in self.prompts():
            if p.name == name:
                return p
        return None

    def namespaces(self) -> list[NamespaceDef]:
        """All Namespace blocks in file order."""
        return [b for b in self.blocks if isinstance(b, NamespaceDef)]

    def namespace_named(self, name: str) -> NamespaceDef | None:
        """Find a namespace by name. Returns None if not found."""
        for ns in self.namespaces():
            if ns.name == name:
                return ns
        return None


# ---------------------------------------------------------------------------
# Block union — top-level constructs
# ---------------------------------------------------------------------------


type Block = StrFragDef | RoleFragDef | PromptDef | NamespaceDef | CommentBlock


# ---------------------------------------------------------------------------
# Fragment definitions
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StrFragDef:
    """StrFrag definition: StrFrag Name[params]: { body }"""

    name: str
    params: list[str] = field(default_factory=list)
    body: list[StrFragBodyItem] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class RoleFragDef:
    """RoleFrag definition: RoleFrag Name[params]: { body }"""

    name: str
    params: list[str] = field(default_factory=list)
    body: list[RoleFragBodyItem] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Prompt definition
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PromptDef:
    """Prompt/chart definition: Name[@T, $param]: { body }"""

    name: str
    indices: list[Expression] = field(default_factory=list)
    body: list[PromptBodyItem] = field(default_factory=list)

    def role_messages(self) -> list[RoleMessage]:
        """All role messages in this prompt body (shallow, not recursive)."""
        return [item for item in self.body if isinstance(item, RoleMessage)]

    def frag_invocations(self) -> list[FragInvocation]:
        """All Frag invocations in this prompt body (shallow, not recursive)."""
        return [item for item in self.body if isinstance(item, FragInvocation)]


# ---------------------------------------------------------------------------
# Namespace definition (non-standard extension)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class NamespaceDef:
    """Namespace block: Namespace name := { bindings }"""

    name: str
    bindings: list[NamespaceBinding] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class NamespaceBinding:
    """A single binding inside a Namespace block: name: type"""

    name: str
    type_expr: str  # e.g. "string", "string[]", "int", "(int,int,int)"


# ---------------------------------------------------------------------------
# Comment
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CommentBlock:
    """A // comment block."""

    text: str


# ---------------------------------------------------------------------------
# Body item unions
# ---------------------------------------------------------------------------


type StrFragBodyItem = (
    ContextVar | TemplateCall | StringLiteral | CommentBlock | ConditionalBlock | LoopBlock | NameDef | FragInvocation
)

type RoleFragBodyItem = (
    RoleMessage | ConditionalBlock | LoopBlock | SwitchBlock | CommentBlock | NameDef | FragInvocation
)

type PromptBodyItem = (
    RoleMessage
    | NamespaceDef
    | ConditionalBlock
    | LoopBlock
    | SwitchBlock
    | NameDef
    | FragInvocation
    | CommentBlock
    | StringLiteral
)

type RoleBodyItem = (
    ContextVar | TemplateCall | StringLiteral | CommentBlock | ConditionalBlock | LoopBlock | SwitchBlock | NameDef | FragInvocation
)


# ---------------------------------------------------------------------------
# Role messages
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RoleMessage:
    """A role-tagged message: S: | U: | A: | T: { body }"""

    role: str  # "system" | "user" | "assistant" | "tool"
    body: list[RoleBodyItem] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Expressions
# ---------------------------------------------------------------------------


type Expression = (
    ContextVar | TemplateCall | StringLiteral | NumberLiteral | NameRef | TimeIndex
    | Comparison | BinaryOp | Identifier
)


@dataclass(frozen=True, slots=True)
class ContextVar:
    """A namespace-prefixed variable: sys.foo, env.bar[@t]"""

    namespace: str  # "env" | "sys" | "resp" | "prompt"
    path: list[str] = field(default_factory=list)
    indices: list[Expression] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class TemplateCall:
    """A template or function call: FUNC(args) or template_name"""

    name: str
    arguments: list[Expression] = field(default_factory=list)
    indices: list[Expression] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class StringLiteral:
    """A double-quoted string literal."""

    value: str


@dataclass(frozen=True, slots=True)
class NumberLiteral:
    """A numeric literal."""

    value: str


@dataclass(frozen=True, slots=True)
class NameRef:
    """A $-prefixed variable reference: $max_iterations"""

    name: str
    indices: list[Expression] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class TimeIndex:
    """An @-prefixed time index: @T, @t"""

    value: Expression  # usually just an identifier like "T" or "t"


@dataclass(frozen=True, slots=True)
class Comparison:
    """A comparison expression: left OP right.

    Only appears at condition level (If, ElseIf).
    """

    left: Expression
    operator: str  # "!=", "==", ">", "<", ">=", "<="
    right: Expression


@dataclass(frozen=True, slots=True)
class BinaryOp:
    """An arithmetic expression: left OP right.

    Appears inside function arguments and index expressions.
    Operators: "+", "-", "*", "/", "%"
    """

    left: Expression
    operator: str
    right: Expression


@dataclass(frozen=True, slots=True)
class Identifier:
    """A bare identifier used as a value — not a namespace prefix, not a $var.

    Used for: Case match values (SkillCalled), the 'none' literal,
    and any other keyword-like identifier appearing in expression position.
    """

    name: str


# ---------------------------------------------------------------------------
# Control flow
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ConditionalBlock:
    """If / ElseIf / Else block."""

    if_condition: Expression | None = None
    if_body: list[PromptBodyItem] = field(default_factory=list)
    else_if_conditions: list[Expression] = field(default_factory=list)
    else_if_bodies: list[list[PromptBodyItem]] = field(default_factory=list)
    else_body: list[PromptBodyItem] | None = None


@dataclass(frozen=True, slots=True)
class LoopBlock:
    """ForEach block: ForEach(var: expr) { body }"""

    variable: str
    iterable: Expression | None = None
    body: list[PromptBodyItem] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class SwitchBlock:
    """Switch / Case / Default block."""

    expression: Expression | None = None
    cases: list[SwitchCase] = field(default_factory=list)
    default_body: list[PromptBodyItem] | None = None


@dataclass(frozen=True, slots=True)
class SwitchCase:
    """A single Case inside a Switch block."""

    match: Expression | None = None
    body: list[PromptBodyItem] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Other
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FragInvocation:
    """Frag Name or Frag Name[args]"""

    name: str
    arguments: list[Expression] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class NameDef:
    """Name varname := expr"""

    name: str
    value: list[Token] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def to_dict(node: object) -> object:
    """Serialize an AST node to plain Python dicts/lists/primitives.

    Returns a JSON-serializable structure suitable for tool output,
    blackboard storage, or comparison with the JS renderer AST.
    """
    if isinstance(node, (str, int, float, bool)) or node is None:
        return node

    if isinstance(node, list):
        return [to_dict(item) for item in node]

    if isinstance(node, tuple):
        return [to_dict(item) for item in node]

    if hasattr(node, "__dataclass_fields__"):
        result: dict[str, object] = {"_type": type(node).__name__}
        for field_name in node.__dataclass_fields__:
            value = getattr(node, field_name)
            # Skip empty defaults to keep output compact
            if value in (None, [], {}):
                continue
            result[field_name] = to_dict(value)
        return result

    # Fallback: Token, other objects
    return str(node)
