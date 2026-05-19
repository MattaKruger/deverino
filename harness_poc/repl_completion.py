from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from prompt_toolkit.completion import Completer, Completion
from textual.suggester import Suggester

if TYPE_CHECKING:
    from collections.abc import Iterable

    from prompt_toolkit.document import Document

    from harness_poc.app_factory import AppState


ROOT_COMMANDS = (
    "/help",
    "/exit",
    "/quit",
    "/workflow",
    "/workflows",
    "/pipeline",
    "/pipelines",
    "/state",
    "/skill",
    "/skills",
    "workflow",
    "pipeline",
    "pipelines",
    "state",
    "skill",
    "exit",
    "quit",
)
STATE_COMMANDS = (
    "show",
    "note",
    "decision",
    "next",
    "question",
    "changelog",
    "propose",
    "approve",
    "reject",
    "consolidate",
)
STATE_SCOPES = ("project", "session", "all")
CONSOLIDATE_MODES = ("preview", "propose", "approve")
SKILL_COMMANDS = ("list", "show", "create")
ROOT_TOKEN_COUNT = 1
SUBCOMMAND_TOKEN_COUNT = 2


@dataclass(frozen=True, slots=True)
class ReplCommandCatalog:
    workflows: tuple[str, ...]
    pipelines: tuple[str, ...]
    skills: tuple[str, ...]

    @classmethod
    def from_app_state(cls, app_state: AppState) -> ReplCommandCatalog:
        return cls(
            workflows=tuple(_workflow_names(app_state)),
            pipelines=tuple(app_state.pipeline_runner.list_pipelines()),
            skills=tuple(_skill_names(app_state)),
        )


class HarnessSuggester(Suggester):
    def __init__(self, app_state: AppState) -> None:
        super().__init__(use_cache=False, case_sensitive=True)
        self.app_state = app_state

    async def get_suggestion(self, value: str) -> str | None:
        suggestion = first_completion(self.app_state, value)
        if suggestion is None:
            return None
        current = _current_token(value)
        return f"{value[: len(value) - len(current)]}{suggestion}"


class HarnessCompleter(Completer):
    def __init__(self, app_state: AppState) -> None:
        self.app_state = app_state

    def get_completions(self, document: Document, complete_event: object) -> Iterable[Completion]:
        del complete_event
        yield from completions_for_text(self.app_state, document.text_before_cursor)


def first_completion(app_state: AppState, text_before_cursor: str) -> str | None:
    return next(
        (completion.text for completion in completions_for_text(app_state, text_before_cursor)),
        None,
    )


def completions_for_text(
    app_state: AppState,
    text_before_cursor: str,
) -> Iterable[Completion]:
    catalog = ReplCommandCatalog.from_app_state(app_state)
    tokens = text_before_cursor.split()
    current = _current_token(text_before_cursor)
    root = tokens[0].removeprefix("/") if tokens else ""

    if not tokens or (len(tokens) == 1 and not text_before_cursor.endswith(" ")):
        yield from _word_completions(_root_words(catalog), current)
        return

    if root == "workflow":
        if len(tokens) == ROOT_TOKEN_COUNT or (
            len(tokens) == SUBCOMMAND_TOKEN_COUNT and not text_before_cursor.endswith(" ")
        ):
            yield from _word_completions(catalog.workflows, current)
        return

    if root == "pipeline":
        if len(tokens) == ROOT_TOKEN_COUNT or (
            len(tokens) == SUBCOMMAND_TOKEN_COUNT and not text_before_cursor.endswith(" ")
        ):
            yield from _word_completions(catalog.pipelines, current)
        return

    if root == "state":
        yield from _state_completions(tokens, current, text_before_cursor)
        return

    if root == "skill":
        yield from _skill_completions(tokens, current, text_before_cursor, catalog)
        return


def _state_completions(
    tokens: list[str], current: str, text_before_cursor: str
) -> Iterable[Completion]:
    if len(tokens) == ROOT_TOKEN_COUNT or (
        len(tokens) == SUBCOMMAND_TOKEN_COUNT and not text_before_cursor.endswith(" ")
    ):
        yield from _word_completions(STATE_COMMANDS, current)
        return

    command = tokens[1] if len(tokens) > 1 else ""
    if command == "show":
        yield from _word_completions(STATE_SCOPES, current)
        return
    if command == "consolidate":
        yield from _word_completions(CONSOLIDATE_MODES, current)


def _skill_completions(
    tokens: list[str],
    current: str,
    text_before_cursor: str,
    catalog: ReplCommandCatalog,
) -> Iterable[Completion]:
    if len(tokens) == ROOT_TOKEN_COUNT or (
        len(tokens) == SUBCOMMAND_TOKEN_COUNT and not text_before_cursor.endswith(" ")
    ):
        yield from _word_completions((*SKILL_COMMANDS, *catalog.skills), current)
        return

    command = tokens[1] if len(tokens) > 1 else ""
    if command == "show":
        yield from _word_completions(catalog.skills, current)


def _word_completions(words: Iterable[str], current: str) -> Iterable[Completion]:
    for word in sorted(words):
        if word.startswith(current):
            yield Completion(word, start_position=-len(current))


def _root_words(catalog: ReplCommandCatalog) -> tuple[str, ...]:
    return (
        *ROOT_COMMANDS,
        *(f"/{name}" for name in catalog.skills),
        *(f"/{name}" for name in catalog.workflows),
        *(f"/{name}" for name in catalog.pipelines),
    )


def _current_token(text_before_cursor: str) -> str:
    if text_before_cursor.endswith(" "):
        return ""
    parts = text_before_cursor.rsplit(maxsplit=1)
    return parts[-1] if parts else ""


def _workflow_names(app_state: AppState) -> list[str]:
    workflows_dir = app_state.config.paths.workflows
    if not workflows_dir.exists():
        return []
    return sorted(path.stem for path in workflows_dir.glob("*.yaml"))


def _skill_names(app_state: AppState) -> list[str]:
    names: list[str] = []
    for tool in app_state.skill_runner.discover_skills():
        function = tool.get("function", {})
        if isinstance(function, dict) and isinstance(function.get("name"), str):
            names.append(function["name"])
    return sorted(names)
