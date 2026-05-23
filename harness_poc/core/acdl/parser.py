"""Recursive-descent parser for Agent Context Definition Language (ACDL).

Implements a fail-fast parser that produces typed ASTs from .acdl source files.
Covers the subset of ACDL used in Deverino harness specification files:
StrFrag, RoleFrag, prompt definitions, Namespace blocks, role messages,
control flow (If/ElseIf/Else, ForEach, Switch/Case/Default), fragment
invocations, context variables, template/function calls, and string literals.

Reference: paper 2605.01920 Appendix D (ACDL specification).
"""

from __future__ import annotations

from harness_poc.core.acdl.ast import (
    ACDLFile,
    CommentBlock,
    ConditionalBlock,
    ContextVar,
    FragInvocation,
    LoopBlock,
    NameDef,
    NamespaceBinding,
    NamespaceDef,
    NumberLiteral,
    PromptDef,
    RoleFragDef,
    RoleMessage,
    StrFragDef,
    StringLiteral,
    SwitchBlock,
    SwitchCase,
    TemplateCall,
    TimeIndex,
    Token,
)

# ---------------------------------------------------------------------------
# Keyword classification (mirrors JS scanner CONTROL_KEYWORDS + NAMESPACE_KEYWORDS)
# ---------------------------------------------------------------------------

_CONTROL_KEYWORDS: frozenset[str] = frozenset({
    "If", "ElseIf", "Else",
    "ForEach", "Switch", "Case", "Default",
    "break", "continue",
    "Name", "for", "in", "Mark",
    "when", "not", "and", "or",
    "StrFrag", "RoleFrag", "Frag",
})

_NAMESPACE_KEYWORDS: frozenset[str] = frozenset({"env", "sys", "resp", "prompt"})

_KEYWORDS: frozenset[str] = _CONTROL_KEYWORDS | _NAMESPACE_KEYWORDS | {"Namespace"}

_NONSTANDARD_ANNOTATIONS: frozenset[str] = frozenset({
    "Struct", "Event", "Pipeline", "Flow", "Fact",
})

_ROLE_IDS: frozenset[str] = frozenset({"S", "U", "A", "T"})

_ROLE_MAP: dict[str, str] = {"S": "system", "U": "user", "A": "assistant", "T": "tool"}

_SYMBOLS: frozenset[str] = frozenset({
    ":", ";", ".", ",", "(", ")", "{", "}", "[", "]",
    "@", "$", "?", "!", "_", "=",
    "<", ">", "&", "|", "^",  # logic ops
    "-", "+", "%", "*", "/",  # arithmetic ops
})


# ---------------------------------------------------------------------------
# Parse error
# ---------------------------------------------------------------------------


class ParseError(Exception):
    """A syntax error with file, line, and column information."""

    def __init__(self, msg: str, line: int, col: int, filename: str = "<string>") -> None:
        self.line = line
        self.col = col
        self.filename = filename
        super().__init__(f"[{filename}:{line}:{col}] {msg}")


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------


class Tokenizer:
    """Lexer that produces a flat token stream from ACDL source text."""

    def __init__(self, source: str, *, filename: str = "<string>") -> None:
        self._source = source
        self._filename = filename
        self._pos = 0
        self._line = 1
        self._col = 1

    def tokenize(self) -> list[Token]:
        tokens: list[Token] = []
        while True:
            tok = self._next_token()
            tokens.append(tok)
            if tok.type == "EOF":
                break
        return tokens

    # -- internals -----------------------------------------------------------

    def _next_token(self) -> Token:
        self._skip_whitespace()
        if self._eof:
            return Token("EOF", "", self._line, self._col)

        ch = self._peek

        if ch == "/" and self._peek_next == "/":
            return self._read_comment()

        if ch == '"':
            return self._read_string()

        if ch in _SYMBOLS:
            return self._read_symbol()

        if ch.isdigit():
            return self._read_number()

        if ch.isalpha() or ch == "_":
            return self._read_identifier()

        raise ParseError(
            f"Unexpected character {ch!r}", self._line, self._col, self._filename,
        )

    def _skip_whitespace(self) -> None:
        while not self._eof and self._peek.isspace():
            if self._peek == "\n":
                self._line += 1
                self._col = 1
            else:
                self._col += 1
            self._pos += 1

    def _read_comment(self) -> Token:
        col = self._col
        self._pos += 2  # skip //
        self._col += 2
        start = self._pos
        while not self._eof and self._source[self._pos] != "\n":
            self._pos += 1
            self._col += 1
        value = self._source[start:self._pos]
        return Token("COMMENT", value, self._line, col)

    def _read_string(self) -> Token:
        col = self._col
        self._pos += 1  # skip opening "
        self._col += 1
        chars: list[str] = []
        while not self._eof:
            ch = self._source[self._pos]
            if ch == '"':
                self._pos += 1
                self._col += 1
                return Token("STRING", "".join(chars), self._line, col)
            if ch == "\\":
                self._pos += 1
                self._col += 1
                if not self._eof:
                    esc = self._source[self._pos]
                    if esc == "n":
                        chars.append("\n")
                    elif esc == "t":
                        chars.append("\t")
                    elif esc in ('"', "\\"):
                        chars.append(esc)
                    else:
                        chars.append(esc)
                    self._pos += 1
                    self._col += 1
                continue
            if ch == "\n":
                self._line += 1
                self._col = 1
            else:
                self._col += 1
            chars.append(ch)
            self._pos += 1
        raise ParseError("Unterminated string literal", self._line, col, self._filename)

    def _read_symbol(self) -> Token:
        col = self._col
        ch = self._source[self._pos]
        self._pos += 1
        self._col += 1
        return Token("SYMBOL", ch, self._line, col)

    def _read_number(self) -> Token:
        col = self._col
        start = self._pos
        while not self._eof and self._source[self._pos].isdigit():
            self._pos += 1
            self._col += 1
        return Token("NUMBER", self._source[start:self._pos], self._line, col)

    def _read_identifier(self) -> Token:
        col = self._col
        start = self._pos
        while not self._eof and (self._source[self._pos].isalnum() or self._source[self._pos] == "_"):
            self._pos += 1
            self._col += 1
        value = self._source[start:self._pos]
        if value in _KEYWORDS:
            return Token("KEYWORD", value, self._line, col)
        return Token("IDENT", value, self._line, col)

    @property
    def _eof(self) -> bool:
        return self._pos >= len(self._source)

    @property
    def _peek(self) -> str:
        return self._source[self._pos]

    @property
    def _peek_next(self) -> str:
        if self._pos + 1 >= len(self._source):
            return ""
        return self._source[self._pos + 1]


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


class Parser:
    """Recursive-descent parser for ACDL source text.

    Usage:
        parser = Parser(source, filename="deverino_react.acdl")
        ast = parser.parse_file()
    """

    def __init__(self, source: str, *, filename: str = "<string>") -> None:
        self._filename = filename
        self._tokens = Tokenizer(source, filename=filename).tokenize()
        self._pos = 0

    # -- public API ----------------------------------------------------------

    def parse_file(self) -> ACDLFile:
        blocks: list = []
        while not self._eof:
            blocks.append(self._parse_top_level())
        return ACDLFile(blocks=blocks)

    # -- helpers -------------------------------------------------------------

    @property
    def _eof(self) -> bool:
        return self._peek.type == "EOF"

    @property
    def _peek(self) -> Token:
        return self._tokens[self._pos]

    def _peek_next(self) -> Token:
        if self._pos + 1 >= len(self._tokens):
            return self._tokens[-1]  # EOF
        return self._tokens[self._pos + 1]

    def _consume(self, typ: str, value: str | None = None) -> Token:
        tok = self._tokens[self._pos]
        if tok.type != typ:
            raise ParseError(
                f"Expected {typ}, got {tok.type} ({tok.value!r})",
                tok.line, tok.col, self._filename,
            )
        if value is not None and tok.value != value:
            raise ParseError(
                f"Expected {typ} {value!r}, got {tok.value!r}",
                tok.line, tok.col, self._filename,
            )
        self._pos += 1
        return tok

    def _consume_ident(self) -> str:
        """Consume an identifier, accepting both IDENT and KEYWORD token types."""
        tok = self._tokens[self._pos]
        if tok.type not in ("IDENT", "KEYWORD"):
            raise ParseError(
                f"Expected identifier, got {tok.type} ({tok.value!r})",
                tok.line, tok.col, self._filename,
            )
        self._pos += 1
        return tok.value

    def _match(self, typ: str, value: str | None = None) -> bool:
        tok = self._tokens[self._pos]
        if tok.type != typ:
            return False
        if value is not None and tok.value != value:
            return False
        self._pos += 1
        return True

    def _err(self, msg: str, tok: Token | None = None) -> ParseError:
        t = tok or self._peek
        return ParseError(msg, t.line, t.col, self._filename)

    # -- top-level blocks ----------------------------------------------------

    def _parse_top_level(self):
        tok = self._peek

        if tok.type == "COMMENT":
            return CommentBlock(text=self._consume("COMMENT").value)

        if tok.type == "KEYWORD":
            if tok.value == "StrFrag":
                return self._parse_str_frag_def()
            if tok.value == "RoleFrag":
                return self._parse_role_frag_def()
            if tok.value == "Namespace":
                return self._parse_namespace_def()
            if tok.value == "Mark":
                self._skip_block()
                return CommentBlock(text="")
            raise self._err(
                f"Unexpected keyword {tok.value!r} at top level", tok,
            )

        if tok.type == "IDENT":
            # Check for non-standard annotations that should be skipped
            if tok.value in _NONSTANDARD_ANNOTATIONS:
                self._skip_block()
                return CommentBlock(text="")
            # Could be a prompt definition: Name[@T]: { ... }
            return self._parse_prompt_def()

        raise self._err(f"Unexpected token {tok.type} ({tok.value!r}) at top level")

    # -- StrFrag definition --------------------------------------------------

    def _parse_str_frag_def(self) -> StrFragDef:
        self._consume("KEYWORD", "StrFrag")
        name = self._consume("IDENT").value
        params = self._parse_optional_params()
        self._consume("SYMBOL", ":")
        self._consume("SYMBOL", "{")
        body: list = []
        while not self._eof and self._peek.value != "}":
            body.append(self._parse_str_frag_body_item())
        self._consume("SYMBOL", "}")
        return StrFragDef(name=name, params=params, body=body)

    def _parse_str_frag_body_item(self):
        tok = self._peek

        if tok.type == "COMMENT":
            return CommentBlock(text=self._consume("COMMENT").value)

        if tok.type == "STRING":
            return StringLiteral(value=self._consume("STRING").value)

        if tok.type == "KEYWORD":
            if tok.value in _NAMESPACE_KEYWORDS:
                return self._parse_context_var()
            if tok.value == "If":
                return self._parse_conditional(self._parse_str_frag_body_item)
            if tok.value == "ForEach":
                return self._parse_loop(self._parse_str_frag_body_item)
            if tok.value == "Frag":
                return self._parse_frag_invocation()
            if tok.value == "Name":
                return self._parse_name_def()
            raise self._err(
                f"Unexpected keyword {tok.value!r} in StrFrag body", tok,
            )

        if tok.type == "IDENT":
            return self._parse_template_or_func()

        raise self._err(
            f"Unexpected token {tok.type} ({tok.value!r}) in StrFrag body",
        )

    # -- RoleFrag definition -------------------------------------------------

    def _parse_role_frag_def(self) -> RoleFragDef:
        self._consume("KEYWORD", "RoleFrag")
        name = self._consume("IDENT").value
        params = self._parse_optional_params()
        self._consume("SYMBOL", ":")
        self._consume("SYMBOL", "{")
        body: list = []
        while not self._eof and self._peek.value != "}":
            body.append(self._parse_role_frag_body_item())
        self._consume("SYMBOL", "}")
        return RoleFragDef(name=name, params=params, body=body)

    def _parse_role_frag_body_item(self):
        tok = self._peek

        if tok.type == "COMMENT":
            return CommentBlock(text=self._consume("COMMENT").value)

        if tok.type == "IDENT" and tok.value in _ROLE_IDS:
            return self._parse_role_message()

        if tok.type == "KEYWORD":
            if tok.value == "If":
                return self._parse_conditional(self._parse_role_frag_body_item)
            if tok.value == "ForEach":
                return self._parse_loop(self._parse_role_frag_body_item)
            if tok.value == "Switch":
                return self._parse_switch(self._parse_role_frag_body_item)
            if tok.value == "Frag":
                return self._parse_frag_invocation()
            if tok.value == "Name":
                return self._parse_name_def()
            raise self._err(
                f"Unexpected keyword {tok.value!r} in RoleFrag body", tok,
            )

        raise self._err(
            f"Unexpected token {tok.type} ({tok.value!r}) in RoleFrag body",
        )

    # -- Prompt definition ---------------------------------------------------

    def _parse_prompt_def(self) -> PromptDef:
        name = self._consume("IDENT").value
        indices = self._parse_optional_indices()
        self._consume("SYMBOL", ":")
        self._consume("SYMBOL", "{")
        body: list = []
        while not self._eof and self._peek.value != "}":
            body.append(self._parse_prompt_body_item())
        self._consume("SYMBOL", "}")
        return PromptDef(name=name, indices=indices, body=body)

    def _parse_prompt_body_item(self):
        tok = self._peek

        if tok.type == "COMMENT":
            return CommentBlock(text=self._consume("COMMENT").value)

        if tok.type == "STRING":
            return StringLiteral(value=self._consume("STRING").value)

        if tok.type == "IDENT" and tok.value in _ROLE_IDS:
            return self._parse_role_message()

        if tok.type == "KEYWORD":
            if tok.value == "Namespace":
                return self._parse_namespace_def()
            if tok.value == "If":
                return self._parse_conditional(self._parse_prompt_body_item)
            if tok.value == "ForEach":
                return self._parse_loop(self._parse_prompt_body_item)
            if tok.value == "Switch":
                return self._parse_switch(self._parse_prompt_body_item)
            if tok.value == "Frag":
                return self._parse_frag_invocation()
            if tok.value == "Mark":
                self._skip_block()
                return CommentBlock(text="")
            if tok.value == "Name":
                return self._parse_name_def()
            raise self._err(
                f"Unexpected keyword {tok.value!r} in prompt body", tok,
            )

        raise self._err(
            f"Unexpected token {tok.type} ({tok.value!r}) in prompt body",
        )

    # -- Namespace definition ------------------------------------------------

    def _parse_namespace_def(self) -> NamespaceDef:
        self._consume("KEYWORD", "Namespace")
        name = self._consume_ident()
        self._consume("SYMBOL", ":")
        self._consume("SYMBOL", "=")  # := is two symbols
        self._consume("SYMBOL", "{")
        bindings: list[NamespaceBinding] = []
        while not self._eof and self._peek.value != "}":
            bindings.append(self._parse_namespace_binding())
        self._consume("SYMBOL", "}")
        return NamespaceDef(name=name, bindings=bindings)

    def _parse_namespace_binding(self) -> NamespaceBinding:
        if self._peek.type == "COMMENT":
            # Full-line comment between bindings — skip
            self._consume("COMMENT")
        binding_name = self._consume_ident()
        self._consume("SYMBOL", ":")
        type_expr = self._parse_type_expr()
        # Optional trailing comment
        if self._peek.type == "COMMENT":
            self._consume("COMMENT")
        return NamespaceBinding(name=binding_name, type_expr=type_expr)

    def _parse_type_expr(self) -> str:
        """Parse a type expression like 'string', 'string[]', '(int,int,int)'."""
        tok = self._peek
        if tok.value == "(":
            # Tuple type: (int, int, int)
            parts: list[str] = []
            self._consume("SYMBOL", "(")
            while not self._eof and self._peek.value != ")":
                parts.append(self._consume("IDENT").value)
                if self._peek.value == ",":
                    self._consume("SYMBOL", ",")
            self._consume("SYMBOL", ")")
            return f"({','.join(parts)})"
        if tok.type == "IDENT":
            base = self._consume("IDENT").value
            if self._peek.value == "[":
                self._consume("SYMBOL", "[")
                self._consume("SYMBOL", "]")
                return f"{base}[]"
            return base
        raise self._err(f"Expected type expression, got {tok.type} ({tok.value!r})")

    # -- Role message --------------------------------------------------------

    def _parse_role_message(self) -> RoleMessage:
        role_id = self._consume("IDENT").value
        role = _ROLE_MAP[role_id]
        self._consume("SYMBOL", ":")

        if self._peek.value == "{":
            self._consume("SYMBOL", "{")
            body: list = []
            while not self._eof and self._peek.value != "}":
                body.append(self._parse_role_body_item())
            self._consume("SYMBOL", "}")
            return RoleMessage(role=role, body=body)

        # Single-line role body
        body = [self._parse_role_body_item_single_line()]
        return RoleMessage(role=role, body=body)

    def _parse_role_body_item(self):
        tok = self._peek

        if tok.type == "COMMENT":
            return CommentBlock(text=self._consume("COMMENT").value)

        if tok.type == "STRING":
            return StringLiteral(value=self._consume("STRING").value)

        if tok.type == "KEYWORD":
            if tok.value in _NAMESPACE_KEYWORDS:
                return self._parse_context_var()
            if tok.value == "If":
                return self._parse_conditional(self._parse_role_body_item)
            if tok.value == "ForEach":
                return self._parse_loop(self._parse_role_body_item)
            if tok.value == "Switch":
                return self._parse_switch(self._parse_role_body_item)
            if tok.value == "Frag":
                return self._parse_frag_invocation()
            if tok.value == "Name":
                return self._parse_name_def()
            raise self._err(
                f"Unexpected keyword {tok.value!r} in role body", tok,
            )

        if tok.type == "IDENT":
            return self._parse_template_or_func()

        raise self._err(
            f"Unexpected token {tok.type} ({tok.value!r}) in role body",
        )

    def _parse_role_body_item_single_line(self):
        """Single-line role body: only context vars and template calls, no strings."""
        tok = self._peek

        if tok.type == "KEYWORD" and tok.value in _NAMESPACE_KEYWORDS:
            return self._parse_context_var()

        if tok.type == "IDENT":
            return self._parse_template_or_func()

        raise self._err(
            f"Unexpected {tok.type} ({tok.value!r}) in single-line role syntax",
        )

    # -- Context variable ----------------------------------------------------

    def _parse_context_var(self) -> ContextVar:
        namespace = self._consume("KEYWORD").value
        self._consume("SYMBOL", ".")
        path_parts: list[str] = [self._consume("IDENT").value]
        while self._peek.value == ".":
            self._consume("SYMBOL", ".")
            path_parts.append(self._consume("IDENT").value)
        indices = self._parse_optional_indices()
        return ContextVar(namespace=namespace, path=path_parts, indices=indices)

    # -- Template / function call --------------------------------------------

    def _parse_template_or_func(self):
        name = self._consume("IDENT").value

        if name == name.upper():
            # ALL_CAPS → template
            args: list = []
            if self._peek.value == "(":
                self._consume("SYMBOL", "(")
                args = self._parse_arguments()
                self._consume("SYMBOL", ")")
            return TemplateCall(name=name, arguments=args)

        if self._peek.value == "(":
            # function call
            self._consume("SYMBOL", "(")
            args = self._parse_arguments()
            self._consume("SYMBOL", ")")
            indices = self._parse_optional_indices()
            return TemplateCall(name=name, arguments=args, indices=indices)

        # Bare identifier with optional dot-path and indices
        # e.g., budget.max_consecutive_tools or just some_var[@t]
        dot_path: list[str] = []
        while self._peek.value == ".":
            self._consume("SYMBOL", ".")
            dot_path.append(self._consume_ident())
        indices = self._parse_optional_indices()
        if dot_path:
            # Treat as context-var-like: first part is "namespace", rest is path
            return ContextVar(namespace=name, path=dot_path, indices=indices)
        return TemplateCall(name=name, indices=indices)

    # -- Fragment invocation -------------------------------------------------

    def _parse_frag_invocation(self) -> FragInvocation:
        self._consume("KEYWORD", "Frag")
        name = self._consume("IDENT").value
        args = self._parse_optional_indices()
        return FragInvocation(name=name, arguments=args)

    # -- Name definition -----------------------------------------------------

    def _parse_name_def(self) -> NameDef:
        self._consume("KEYWORD", "Name")
        name = self._consume("IDENT").value
        self._consume("SYMBOL", ":")
        self._consume("SYMBOL", "=")  # :=
        value_tokens = self._collect_until_semicolon_or_newline()
        return NameDef(name=name, value=value_tokens)

    # -- Control flow --------------------------------------------------------

    def _parse_conditional(self, body_parser) -> ConditionalBlock:
        self._consume("KEYWORD", "If")
        if_condition = self._collect_until_brace()
        self._consume("SYMBOL", "{")
        if_body = self._parse_body_until("}", body_parser)
        self._consume("SYMBOL", "}")

        else_if_conditions: list[list[Token]] = []
        else_if_bodies: list[list] = []
        else_body: list | None = None

        while self._peek.type == "KEYWORD" and self._peek.value in ("ElseIf", "Else"):
            kw = self._consume("KEYWORD").value
            if kw == "ElseIf":
                cond = self._collect_until_brace()
                self._consume("SYMBOL", "{")
                body = self._parse_body_until("}", body_parser)
                self._consume("SYMBOL", "}")
                else_if_conditions.append(cond)
                else_if_bodies.append(body)
            else:  # Else
                self._consume("SYMBOL", "{")
                else_body = self._parse_body_until("}", body_parser)
                self._consume("SYMBOL", "}")
                break

        return ConditionalBlock(
            if_condition=if_condition,
            if_body=if_body,
            else_if_conditions=else_if_conditions,
            else_if_bodies=else_if_bodies,
            else_body=else_body,
        )

    def _parse_loop(self, body_parser) -> LoopBlock:
        self._consume("KEYWORD", "ForEach")
        self._consume("SYMBOL", "(")
        # Variable can be @time or plain identifier
        if self._peek.value == "@":
            self._consume("SYMBOL", "@")
            variable = "@" + self._consume("IDENT").value
        else:
            variable = self._consume("IDENT").value
        self._consume("SYMBOL", ":")
        iterable = self._collect_until(")")
        self._consume("SYMBOL", ")")
        self._consume("SYMBOL", "{")
        body = self._parse_body_until("}", body_parser)
        self._consume("SYMBOL", "}")
        return LoopBlock(variable=variable, iterable=iterable, body=body)

    def _parse_switch(self, body_parser) -> SwitchBlock:
        self._consume("KEYWORD", "Switch")
        expression = self._collect_until_brace()
        self._consume("SYMBOL", "{")
        cases: list[SwitchCase] = []
        default_body: list | None = None

        while not self._eof and self._peek.value != "}":
            if self._peek.type == "COMMENT":
                # Skip comments between cases
                self._consume("COMMENT")
                continue
            kw = self._consume("KEYWORD")
            if kw.value == "Case":
                match = self._collect_until_brace()
                self._consume("SYMBOL", "{")
                body = self._parse_body_until("}", body_parser)
                self._consume("SYMBOL", "}")
                cases.append(SwitchCase(match=match, body=body))
            elif kw.value == "Default":
                self._consume("SYMBOL", "{")
                default_body = self._parse_body_until("}", body_parser)
                self._consume("SYMBOL", "}")
            else:
                raise self._err(
                    f"Expected Case or Default in Switch, got {kw.value!r}", kw,
                )

        self._consume("SYMBOL", "}")
        return SwitchBlock(expression=expression, cases=cases, default_body=default_body)

    # -- Expression / argument parsing ---------------------------------------

    def _parse_arguments(self) -> list:
        """Parse comma-separated arguments inside parentheses."""
        args: list = []
        if self._peek.value in (")", "]"):
            return args
        while True:
            args.append(self._parse_expression())
            if not self._match("SYMBOL", ","):
                break
        return args

    def _parse_expression(self):
        """Parse a single expression atom for use in arguments or indices."""
        tok = self._peek

        if self._match("SYMBOL", "@"):
            # Time index: @T, @t
            inner = self._parse_expression()
            return TimeIndex(value=inner)

        if tok.type == "STRING":
            return StringLiteral(value=self._consume("STRING").value)

        if tok.type == "NUMBER":
            return NumberLiteral(value=self._consume("NUMBER").value)

        if tok.type == "KEYWORD" and tok.value in _NAMESPACE_KEYWORDS:
            return self._parse_context_var()

        if tok.type == "IDENT":
            return self._parse_template_or_func()

        if tok.type == "SYMBOL" and tok.value == "$":
            self._consume("SYMBOL", "$")
            name = self._consume("IDENT").value
            indices = self._parse_optional_indices()
            return ContextVar(namespace="$", path=[name], indices=indices)

        raise self._err(
            f"Unexpected token {tok.type} ({tok.value!r}) in expression",
        )

    # -- Optional / helper parsers -------------------------------------------

    def _parse_optional_params(self) -> list[str]:
        """Parse optional [param1, param2] after fragment/prompt name."""
        params: list[str] = []
        if self._peek.value == "[":
            self._consume("SYMBOL", "[")
            if self._peek.value != "]":
                while True:
                    tok = self._peek
                    if tok.type == "SYMBOL" and tok.value == "$":
                        self._consume("SYMBOL", "$")
                        params.append("$" + self._consume("IDENT").value)
                    elif tok.type == "SYMBOL" and tok.value == "@":
                        self._consume("SYMBOL", "@")
                        params.append("@" + self._consume("IDENT").value)
                    elif tok.type == "IDENT":
                        params.append(self._consume("IDENT").value)
                    else:
                        break
                    if not self._match("SYMBOL", ","):
                        break
            self._consume("SYMBOL", "]")
        return params

    def _parse_optional_indices(self) -> list:
        """Parse optional [expr, expr, ...] index lists."""
        indices: list = []
        while self._peek.value == "[":
            self._consume("SYMBOL", "[")
            if self._peek.value != "]":
                while True:
                    indices.append(self._parse_expression())
                    if not self._match("SYMBOL", ","):
                        break
            self._consume("SYMBOL", "]")
        return indices

    def _skip_block(self) -> None:
        """Skip a non-standard annotation block (Mark, Struct, etc.)."""
        # Skip tokens until we find the opening brace
        while not self._eof and self._peek.value != "{":
            self._pos += 1
        if self._peek.value == "{":
            self._pos += 1
            depth = 1
            while not self._eof and depth > 0:
                if self._peek.value == "{":
                    depth += 1
                elif self._peek.value == "}":
                    depth -= 1
                self._pos += 1

    # -- Token collection helpers --------------------------------------------

    def _collect_until(self, stop_value: str) -> list[Token]:
        """Collect raw tokens until a symbol with the given value is found."""
        tokens: list[Token] = []
        depth = 0
        while not self._eof:
            tok = self._peek
            if tok.value == "(":
                depth += 1
            elif tok.value == ")":
                if depth == 0:
                    break
                depth -= 1
            elif tok.value == stop_value and depth == 0:
                break
            tokens.append(tok)
            self._pos += 1
        return tokens

    def _collect_until_brace(self) -> list[Token]:
        """Collect raw tokens until an opening brace {."""
        return self._collect_until("{")

    def _collect_until_semicolon_or_newline(self) -> list[Token]:
        """Collect raw tokens until end of line (for NameDef values)."""
        tokens: list[Token] = []
        start_line = self._peek.line
        while not self._eof and self._peek.line == start_line:
            tok = self._peek
            if tok.value == ";":
                break
            tokens.append(tok)
            self._pos += 1
        return tokens

    def _parse_body_until(self, stop_value: str, body_parser) -> list:
        """Parse body items using the given parser until a specific closing symbol."""
        items: list = []
        while not self._eof and self._peek.value != stop_value:
            items.append(body_parser())
        return items
