---
title: "TUI Keybindings Reference"
date: 2026-06-13
status: draft
kind: guide
---
# TUI Keybindings Reference

Current as of 2026-06-13. Covers both default (insert-mode) and Vim-modal keybindings.

## Architecture

Three dispatch layers, in priority order:

1. **`ChatApp.BINDINGS`** — Textual priority bindings, app-wide, always fire first.
2. **`VimTextArea._on_key`** — widget-level hook for input pane Vim (when Vim enabled, input focused).
3. **`ChatApp.on_key`** — app-level handler for chat pane Vim (when Vim enabled, chat focused).

See `harness_poc/tui.py` for the router and `harness_poc/tui_vim.py` for the Vim handlers.

---

## Global Shortcuts (always active)

These are defined in `ChatApp.BINDINGS` with `priority=True`. They work regardless of Vim state.

| Key | Action | Notes |
|---|---|---|
| `Super+C` | Copy smart | Prefers screen selection, falls back to input field |
| `Super+Y` | Copy last response | Copies the last assistant message to clipboard |
| `Ctrl+D` | Submit editor | **BUG: double-scrolls in chat Vim pane (see below)** |
| `Alt+Enter` | Submit editor | Submits current input text |
| `Super+Enter` | Submit editor | Submits current input text |
| `Tab` | Cycle completion / cycle pane | See [Tab behavior](#tab-behavior) |
| `Shift+Tab` | Cycle completion backward / cycle pane | See [Tab behavior](#tab-behavior) |
| `Enter` | Accept completion or newline | Accepts visible completion; otherwise inserts newline |
| `F2` | Toggle Vim mode | Enables/disables Vim modal layer |

### Enter / Submit separation

`Enter` inserts a newline in the multi-line input editor. To **submit** the prompt, use `Ctrl+D`, `Alt+Enter`, or `Super+Enter`.

### Tab behavior

Tab is semantically overloaded based on runtime state:

| Completion visible? | Vim enabled? | Tab does |
|---|---|---|
| Yes | Any | Cycle completions forward |
| No | No | Open completion menu |
| No | Yes | Cycle input ↔ chat pane |

`Shift+Tab` mirrors this (cycle backward / cycle panes backward).

---

## Vim Mode

Toggled with `F2`. Configurable in `harness.yaml`:

```yaml
tui:
  vim_enabled: false
  vim_initial_mode: insert   # or "normal"
```

Vim uses a two-pane focus model:

- **Input pane** — the prompt `TextArea` (editable buffer)
- **Chat pane** — the transcript `VerticalScroll` (read-only buffer)

The status line (`#vim-status`) shows current mode and pane: `INSERT input`, `NORMAL chat`, etc. When Vim is off it shows `vim off`.

---

## Input Pane — Insert Mode

Default mode. Typing inserts text normally. `Escape` enters normal mode. All other keys behave as standard TextArea input.

---

## Input Pane — Normal Mode

| Key | Behavior |
|---|---|
| `i` | Enter insert mode |
| `a` | Move right, then enter insert mode |
| `A` | Move to line end, then enter insert mode |
| `h` / `j` / `k` / `l` | Cursor left / down / up / right |
| `0` | Line start |
| `$` | Line end |
| `w` | Word right |
| `b` | Word left |
| `x` | Delete character under cursor |
| `D` | Delete to end of line |
| `u` | Undo |
| `v` | Enter visual mode |
| `d{motion}` | Delete from cursor to motion target (`dw`, `d$`, `d0`, `dh`, `dl`, etc.) |
| `c{motion}` | Delete from cursor to motion target, then enter insert mode |
| `dd` | Delete current line |
| `cc` | Clear current line, then enter insert mode |
| `{count}{command}` | Repeat command `{count}` times (e.g. `3j` moves down 3 lines) |
| `Escape` | Clear pending operator/count |

Motion keys usable after `d`/`c`: `h`, `j`, `k`, `l`, `w`, `b`, `0`, `$`.

### Input Pane — Visual Mode

| Key | Behavior |
|---|---|
| `h` / `j` / `k` / `l` | Extend selection |
| `w` / `b` | Extend selection by word |
| `0` / `$` | Extend selection to line edge |
| `y` | Copy selection, return to normal mode |
| `d` | Delete selection, return to normal mode |
| `c` | Delete selection, enter insert mode |
| `v` | Return to normal mode (clear selection) |
| `Escape` | Return to normal mode (clear selection) |

---

## Chat Pane — Normal Mode

Chat pane is **read-only**. No insert mode in chat — pressing `i` switches focus back to the input pane in insert mode.

| Key | Behavior |
|---|---|
| `j` | Scroll down one line |
| `k` | Scroll up one line |
| `Ctrl+D` | Scroll down half page |
| `Ctrl+U` | Scroll up half page |
| `gg` | Scroll to top |
| `G` | Scroll to bottom |
| `i` | Focus input pane, enter insert mode |
| `v` | Enter chat visual mode (select messages) |
| `Y` | Copy last assistant response |
| `{count}{j,k}` | Scroll `{count}` lines (e.g. `5j` scrolls down 5 lines) |
| `Escape` | Clear pending operator/count |

### Chat Pane — Visual Mode

Selects message blocks by index (not characters). Messages are joined with `\n\n` on copy.

| Key | Behavior |
|---|---|
| `j` | Extend selection down one message |
| `k` | Extend selection up one message |
| `y` | Copy selected message range, return to normal |
| `v` | Return to normal mode (clear selection) |
| `Escape` | Return to normal mode (clear selection) |

---

## Completion Menu (visible)

When the completion menu is open:

| Key | Behavior |
|---|---|
| `Tab` | Next completion |
| `Shift+Tab` | Previous completion |
| `Enter` | Accept highlighted completion |
| `Escape` | (Standard Textual — closes menu) |
| Any other key | Closes menu, passes through to input |

The completion menu takes priority over Vim pane cycling and Vim keybindings. If the menu is visible, `Tab`/`Shift+Tab` always cycle completions — never panes.

---

## Known Issues

### Fixed 2026-06-13: ctrl+d/enter leaked in NORMAL mode

Previously, `ctrl+d` and `enter` fired unconditionally even when Vim was in NORMAL mode
on the input pane — `ctrl+d` would accidentally submit, `enter` would insert a newline.
Both action handlers now check `_vim.mode == VimMode.NORMAL` and swallow the key.

### Fixed 2026-06-13: dead ctrl+d handler removed from ChatVimHandler

The `ChatVimHandler._handle_normal` method handled `ctrl+d` as a scroll, but the
BINDINGS-level `ctrl+d` binding always consumed the event first. The dead handler
was removed — `ctrl+d` in chat pane is handled exclusively by `action_submit_editor`.

### Tab semantics are implicit

Tab means three different things depending on Vim state and completion visibility. This
is implemented correctly but not surfaced in the UI — the vim-status line shows
mode/pane but doesn't indicate whether Tab will cycle completions or panes.

---

## File Reference

| File | Responsibility |
|---|---|
| `harness_poc/tui.py` | `ChatApp.BINDINGS`, key routing, completion handling, spinner, chat worker |
| `harness_poc/tui_vim.py` | `VimState`, `InputVimHandler`, `ChatVimHandler`, key normalization |
| `harness_poc/core/config.py` | `TuiConfig` — `vim_enabled`, `vim_initial_mode` |
| `tests/repl/test_tui.py` | Integration tests: compose, exit, tab, enter, submit, vim modes |
| `tests/repl/test_tui_vim.py` | Unit tests: state, insert, normal, operator+motion, visual, chat handler |
