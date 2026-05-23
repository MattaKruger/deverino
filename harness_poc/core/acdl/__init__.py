"""ACDL parser — Python-side parser for Agent Context Definition Language files.

Provides parse() and validate() for .acdl specification files used in the
Deverino harness. Produces typed ASTs for programmatic inspection and
structural validation.
"""

from harness_poc.core.acdl.ast import ACDLFile, to_dict
from harness_poc.core.acdl.parser import ParseError, Parser

__all__ = ["ACDLFile", "ParseError", "Parser", "parse", "to_dict", "validate"]


def parse(source: str, *, filename: str = "<string>") -> ACDLFile:
    """Parse ACDL source into an AST. Raises ParseError on failure."""
    parser = Parser(source, filename=filename)
    return parser.parse_file()


def validate(source: str, *, filename: str = "<string>") -> list[str]:
    """Validate ACDL source. Returns a list of error messages (empty = valid)."""
    try:
        parse(source, filename=filename)
    except ParseError as e:
        return [str(e)]
    return []
