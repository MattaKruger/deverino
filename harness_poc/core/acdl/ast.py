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


type Expression = ContextVar | TemplateCall | StringLiteral | NumberLiteral | NameRef | TimeIndex


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


# ---------------------------------------------------------------------------
# Control flow
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ConditionalBlock:
    """If / ElseIf / Else block."""

    if_condition: list[Token] = field(default_factory=list)
    if_body: list[PromptBodyItem] = field(default_factory=list)
    else_if_conditions: list[list[Token]] = field(default_factory=list)
    else_if_bodies: list[list[PromptBodyItem]] = field(default_factory=list)
    else_body: list[PromptBodyItem] | None = None


@dataclass(frozen=True, slots=True)
class LoopBlock:
    """ForEach block: ForEach(var: expr) { body }"""

    variable: str
    iterable: list[Token] = field(default_factory=list)
    body: list[PromptBodyItem] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class SwitchBlock:
    """Switch / Case / Default block."""

    expression: list[Token] = field(default_factory=list)
    cases: list[SwitchCase] = field(default_factory=list)
    default_body: list[PromptBodyItem] | None = None


@dataclass(frozen=True, slots=True)
class SwitchCase:
    """A single Case inside a Switch block."""

    match: list[Token] = field(default_factory=list)
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
