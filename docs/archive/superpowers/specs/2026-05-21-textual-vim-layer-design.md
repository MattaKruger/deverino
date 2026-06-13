# Textual Vim Layer Design

**Date:** 2026-05-21
**Status:** draft
**Author:** Matthijs Kruger

## Goal

Add an optional Vim-style modal interaction layer to the Textual TUI. The layer should work across both the prompt editor and the chat/history pane, using a tab-focused pane model so keybindings are routed by the currently active pane.

The feature must be fully disabled when the Vim toggle is off. In that state, the existing Textual TUI behavior remains unchanged.

## Current Implementation Review

The Textual UI is currently concentrated in `harness_poc/tui.py`.

Relevant existing behavior:

- `ChatApp.BINDINGS` defines app-level shortcuts for copy, submit, completion cycling, and newline insertion.
- The prompt editor is a Textual `TextArea` with `id="input"`.
- The chat transcript is a `VerticalScroll` with `id="chat"`.
- The completion menu is an `OptionList` with `id="completion-menu"`.
- `tab` and `shift+tab` currently cycle completions.
- `enter` accepts a visible completion, otherwise inserts a newline.
- `ctrl+d`, `alt+enter`, and `super+enter` submit the prompt.
- Submitted text is routed through `handle_repl_input`, so business logic remains outside the TUI.

This is a good fit for a Vim layer because all interaction state can live in the TUI layer. No changes are needed to skills, workflows, the blackboard, the LLM runtime, or REPL command dispatch.

The current checkout does not contain a `vim` or `tui` config section. If a Vim toggle exists on another branch, it should be normalized into the config/state model described below rather than introducing a second toggle path.

## Scope

### In Scope

- Optional Vim mode controlled by config and a live TUI toggle.
- Input pane modal editing with insert, normal, and visual modes.
- Chat/history pane modal navigation with normal and visual modes.
- Tab-based pane focus between input and chat/history.
- Completion menu priority over pane cycling.
- Mode and pane indicator in the TUI.
- Focused tests for enabled and disabled behavior.

### Out of Scope

- Full Vim emulation.
- Vim macros, marks, registers beyond a simple yank buffer, ex command history, or plugin compatibility.
- Character-perfect visual selection over Rich-rendered Markdown.
- Changes to REPL command semantics.
- Changes to model/tool execution.

## User Model

The interaction model should feel close to using Vim in an editor like Zed:

- The user can be in `insert`, `normal`, or `visual` mode.
- The active pane determines where Vim commands apply.
- The input pane behaves like an editable buffer.
- The chat/history pane behaves like a navigable read-only buffer.
- `tab` and `shift+tab` cycle panes at the TUI level.
- Completion menu navigation temporarily overrides pane cycling.

## Configuration

Add a TUI config section:

```yaml
tui:
  vim_enabled: false
  vim_initial_mode: insert
```

Add config types in `harness_poc/core/config.py`:

```python
@dataclass(frozen=True, slots=True)
class TuiConfig:
    vim_enabled: bool = False
    vim_initial_mode: str = "insert"
```

Extend `HarnessConfig`:

```python
@dataclass(frozen=True, slots=True)
class HarnessConfig:
    ...
    tui: TuiConfig = field(default_factory=TuiConfig)
```

Parsing rule:

- Missing `tui` section defaults to Vim disabled.
- `vim_initial_mode` accepts `insert` or `normal`.
- Invalid values raise `ValueError` at config load time.
- If an existing toggle already exists elsewhere, map it into `TuiConfig.vim_enabled`.

## Runtime State

Create a new module:

```text
harness_poc/tui_vim.py
```

Define the modal state there:

```python
from dataclasses import dataclass
from enum import StrEnum


class VimMode(StrEnum):
    INSERT = "insert"
    NORMAL = "normal"
    VISUAL = "visual"


class VimPane(StrEnum):
    INPUT = "input"
    CHAT = "chat"


@dataclass(slots=True)
class VimState:
    enabled: bool
    pane: VimPane = VimPane.INPUT
    mode: VimMode = VimMode.INSERT
    pending: str = ""
    count: int | None = None
```

`ChatApp` owns one `VimState`.

The state is UI-only. It should not be persisted to the blackboard.

## Widget Structure

Keep the current widget hierarchy and add a lightweight status indicator:

```text
ChatApp
+-- Static (id="header")
+-- VerticalScroll (id="chat")
+-- Vertical (id="footer")
    +-- Static (id="spinner")
    +-- Static (id="vim-status")
    +-- TextArea (id="input")
    +-- OptionList (id="completion-menu")
```

The status line should be one row high and render compact text:

```text
vim off
INSERT input
NORMAL input
VISUAL chat
```

CSS changes:

- Add `#vim-status { height: 1; color: $text-muted; padding: 0 1; }`.
- Increase `#footer` height by one row.
- Add focused-pane styling for `#input` and `#chat` if Textual supports it cleanly. If not, status text is sufficient for the first implementation.

## Pane Focus Model

The app has two primary panes:

- `input`: editable prompt `TextArea`
- `chat`: transcript/history `VerticalScroll`

Rules:

```text
if completion menu is visible:
    tab cycles completion options
    shift+tab cycles completion options backward
else:
    tab cycles input -> chat -> input
    shift+tab cycles input -> chat -> input
```

Pane focus and Vim mode are separate:

- Changing pane does not automatically disable Vim.
- Switching to the chat pane from input normal mode keeps normal mode.
- Switching to the input pane from chat via `i` enters insert mode.
- The chat pane does not use insert mode for editing. If chat is focused and the user presses `i`, focus returns to the input pane in insert mode.

## Key Event Routing

`ChatApp` should have one top-level key routing path for Vim behavior:

```python
def on_key(self, event: Key) -> None:
    if self._completion_visible:
        self._handle_completion_key(event)
        return

    if event.key in {"tab", "shift+tab"}:
        self._cycle_vim_pane(backward=event.key == "shift+tab")
        event.stop()
        event.prevent_default()
        return

    if not self._vim.enabled:
        return

    if self._vim.pane == VimPane.INPUT:
        handled = self._vim_input.handle(event, self.query_one("#input", TextArea))
    else:
        handled = self._vim_chat.handle(event, self.query_one("#chat", VerticalScroll))

    if handled:
        event.stop()
        event.prevent_default()
```

Important: this router must preserve existing Textual behavior when Vim is disabled.

## Input Pane Behavior

The input pane operates on the `TextArea`.

### Insert Mode

Keys behave like normal `TextArea` typing, except:

- `esc` enters normal mode.
- The live Vim toggle can turn Vim off.
- Existing submit keys continue to submit.
- Existing completion behavior continues to work.

### Normal Mode

Minimum supported commands:

| Key       | Behavior                         |
| --------- | -------------------------------- |
| `i`       | enter insert mode                |
| `a`       | move right, enter insert mode    |
| `A`       | move to line end, insert mode    |
| `h`       | cursor left                      |
| `j`       | cursor down                      |
| `k`       | cursor up                        |
| `l`       | cursor right                     |
| `0`       | line start                       |
| `$`       | line end                         |
| `w`       | word right                       |
| `b`       | word left                        |
| `x`       | delete character under cursor    |
| `D`       | delete to end of line            |
| `dd`      | delete current line              |
| `u`       | undo                             |
| `v`       | enter visual mode                |
| `esc`     | clear pending command/count      |

Use existing `TextArea` actions where possible:

- `action_cursor_left`
- `action_cursor_right`
- `action_cursor_up`
- `action_cursor_down`
- `action_cursor_line_start`
- `action_cursor_line_end`
- `action_cursor_word_left`
- `action_cursor_word_right`
- `action_delete_right`
- `action_delete_to_end_of_line`
- `action_delete_line`
- `action_undo`

### Visual Mode

Minimum supported commands:

| Key       | Behavior                         |
| --------- | -------------------------------- |
| `h/j/k/l` | extend selection                 |
| `w/b`     | extend selection by word         |
| `0/$`     | extend selection to line edge    |
| `y`       | copy selection, return normal    |
| `d`       | delete selection, return normal  |
| `c`       | delete selection, enter insert   |
| `esc`     | clear selection, return normal   |

The input visual mode may use `TextArea.move_cursor(..., select=True)`.

## Chat Pane Behavior

The chat pane is read-only. Its Vim behavior is navigation and copy oriented.

### Normal Mode

Minimum supported commands:

| Key        | Behavior                              |
| ---------- | ------------------------------------- |
| `j`        | scroll down one line                  |
| `k`        | scroll up one line                    |
| `ctrl+d`   | scroll down half page                 |
| `ctrl+u`   | scroll up half page                   |
| `gg`       | scroll to top                         |
| `G`        | scroll to bottom                      |
| `i`        | focus input pane, enter insert mode   |
| `v`        | enter chat visual mode                |
| `Y`        | copy latest assistant response        |
| `esc`      | clear pending command/count           |

Optional second pass:

| Key        | Behavior                              |
| ---------- | ------------------------------------- |
| `/`        | start transcript search               |
| `n`        | next search match                     |
| `N`        | previous search match                 |
| `enter`    | open link/file under current cursor   |

### Visual Mode

Character-perfect visual selection over rendered Markdown is not required for the first implementation. Use message-block or line-block selection.

Minimum behavior:

| Key        | Behavior                              |
| ---------- | ------------------------------------- |
| `j`        | extend selected transcript block down |
| `k`        | extend selected transcript block up   |
| `y`        | copy selected transcript text         |
| `esc`      | clear selection, return normal        |

Implementation approach:

- Track chat message widgets as they are mounted.
- Store plain text content for each mounted user, tool, and assistant message.
- Maintain a selected index range in chat visual mode.
- Apply a CSS class to selected widgets if practical.
- Copy joined plain text for the selected range.

## Live Toggle

Add one app-level binding:

```python
Binding("f2", "toggle_vim", "Toggle Vim", priority=True, show=False)
```

`action_toggle_vim`:

```python
def action_toggle_vim(self) -> None:
    self._vim.enabled = not self._vim.enabled
    self._vim.pending = ""
    self._vim.count = None
    self._vim.pane = VimPane.INPUT
    self._vim.mode = (
        VimMode.INSERT
        if not self._vim.enabled
        else self._configured_initial_vim_mode
    )
    self.query_one("#input", TextArea).focus()
    self._hide_completion_menu()
    self._update_vim_status()
```

When disabled:

- Do not intercept printable keys.
- Do not intercept `esc` for Vim.
- Keep existing completion and submit behavior.
- Status renders `vim off`.

When enabled:

- Initial pane is `input`.
- Initial mode comes from config.
- Pending operator/count state is empty.

## Completion Menu Precedence

The completion menu must have priority over Vim pane cycling and Vim keybindings.

Rules:

- If the completion menu is visible, `tab`, `shift+tab`, and `enter` preserve their current completion behavior.
- `esc` closes the completion menu and returns focus to input.
- After accepting or closing a completion, routing returns to the normal pane/mode model.

This avoids breaking the existing completion tests.

## Suggested File Changes

| File | Change |
| ---- | ------ |
| `harness_poc/core/config.py` | Add `TuiConfig`, parse `tui`, add to `HarnessConfig` |
| `harness.yaml` | Add `tui.vim_enabled` and `tui.vim_initial_mode` defaults |
| `harness_poc/tui_vim.py` | New Vim state, enums, key parser, input/chat handlers |
| `harness_poc/tui.py` | Wire state, status widget, pane cycling, toggle, key routing |
| `tests/test_config.py` or existing config tests | Cover TUI config defaults and parsing |
| `tests/test_tui.py` | Cover enabled/disabled routing, modes, pane cycling, completions |

## Implementation Phases

### Phase 1: Config and Status

- Add `TuiConfig`.
- Parse `tui` from `harness.yaml`.
- Initialize `VimState` in `ChatApp`.
- Add `#vim-status`.
- Add `action_toggle_vim`.
- Tests:
  - Missing `tui` config defaults to disabled.
  - `vim_enabled: true` starts Vim enabled.
  - Toggle resets pane/mode/pending state.

### Phase 2: Pane Cycling

- Add `VimPane`.
- Implement `tab` and `shift+tab` pane cycling when completion is hidden.
- Preserve existing completion menu behavior when visible.
- Tests:
  - Vim disabled keeps existing text entry behavior.
  - Completion menu still consumes `tab`, `shift+tab`, and `enter`.
  - With completion hidden, `tab` cycles input and chat pane state.

### Phase 3: Input Normal and Insert Modes

- Intercept input pane keys only when Vim is enabled.
- Add `esc`, `i`, `a`, `A`.
- Add basic movement: `h/j/k/l`, `0`, `$`, `w`, `b`.
- Add simple edits: `x`, `D`, `dd`, `u`.
- Tests:
  - In insert mode, typed keys become text.
  - `esc` enters normal mode.
  - In normal mode, `j` and `k` do not insert characters.
  - `i` returns to insert mode.
  - Existing submit keys still submit.

### Phase 4: Input Visual Mode

- Add `v`.
- Add selection-extending motions.
- Add `y`, `d`, `c`, `esc`.
- Tests:
  - Visual movement selects text.
  - `y` copies and returns normal.
  - `d` removes selection.
  - `c` removes selection and enters insert.

### Phase 5: Chat Normal Mode

- Add chat pane scroll commands.
- Add `i` to focus input and enter insert mode.
- Add `Y` using existing latest-response copy logic.
- Tests:
  - Chat `j/k` scrolls instead of editing prompt text.
  - Chat `i` focuses input and enters insert.
  - `Y` calls copy latest response behavior.

### Phase 6: Chat Visual Mode

- Track mounted chat message text and widget references.
- Add message-block selection range.
- Add `v`, `j/k`, `y`, `esc`.
- Tests:
  - Visual range expands and contracts.
  - `y` copies selected transcript text.
  - `esc` clears visual state.

### Phase 7: Counts and Operator Motions

- Add count prefix parsing.
- Add operator pending state for `d` and `c`.
- Support `3j`, `2w`, `dw`, `d$`, `cw`, `cc`.
- Tests:
  - Counts repeat motion.
  - Operators combine with motions.
  - Invalid pending sequences clear cleanly on `esc`.

## Test Strategy

Use Textual pilot tests where possible. Keep pure key parsing logic in `tui_vim.py` so it can be unit tested without running a full Textual app.

Required regression tests:

- Existing `tests/test_tui.py` tests pass unchanged when Vim is disabled.
- Completion menu precedence is preserved.
- Submit bindings are preserved.
- Toggling Vim off restores normal printable-key behavior.
- No business logic tests need to change.

Focused unit tests:

- `VimState` initialization.
- Mode transitions.
- Pending operator handling.
- Count parsing.
- Pane routing decisions.

## Risks

### TextArea key interception

Textual `TextArea` may consume printable keys before app-level handlers in some cases. If app-level `on_key` cannot reliably intercept normal-mode printable keys, introduce a small subclass:

```python
class VimTextArea(TextArea):
    def on_key(self, event: Key) -> None:
        app = cast("ChatApp", self.app)
        if app.handle_vim_text_area_key(event):
            event.stop()
            event.prevent_default()
```

Use this subclass only for the prompt widget.

### Completion conflicts

The existing completion flow relies on `tab`, `shift+tab`, and `enter`. Completion visibility must be checked before Vim routing.

### Visual selection in chat

Rendered Markdown is not a normal text buffer. Message-block visual mode avoids coupling to Rich internals and is acceptable for the initial implementation.

### Toggle expectations

Users may expect the toggle to preserve current mode. This spec resets to a predictable state when toggled:

- off: input pane, insert mode, no pending command
- on: input pane, configured initial mode, no pending command

This behavior should be documented in the status line or help text if a help screen is added later.

## Acceptance Criteria

- With Vim disabled, the current TUI tests and behavior remain unchanged.
- With Vim enabled, the prompt supports insert, normal, and visual mode.
- With Vim enabled, the chat pane supports normal and visual navigation/copy behavior.
- `tab` cycles panes unless the completion menu is visible.
- Completion menu behavior is unchanged while visible.
- The live toggle turns Vim behavior off and on without restarting the app.
- The current mode and pane are visible in the TUI.
- The implementation is isolated to TUI/config code and does not change REPL command execution.
