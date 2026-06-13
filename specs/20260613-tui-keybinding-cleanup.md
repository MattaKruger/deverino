---
title: "TUI Keybinding Cleanup — Audit, Fix, and Unify"
date: 2026-06-13
status: draft
kind: spec
---
# TUI Keybinding Cleanup — Audit, Fix, and Unify

## Objective

Fix the fragmented keybinding architecture in the Textual TUI. Consolidate dispatch into a single
coherent router, eliminate dead code, fix Vim-mode key leaks, and bring the UX in line with
top-tier modal TUI conventions.

## Background

The current keybinding system (documented in `docs/guides/tui-keybindings.md`) has three parallel
dispatch layers that interact implicitly:

| Layer | Mechanism | When it fires | Purpose |
|---|---|---|---|
| `ChatApp.BINDINGS` | Textual priority bindings | Before any widget/`on_key` handler | Global shortcuts |
| `VimTextArea._on_key` | Widget-level key hook | After bindings, before TextArea | Input pane Vim |
| `ChatApp.on_key` | App-level handler | After widget, if unhandled | Chat pane Vim |

Textual 8.2.7's `App._on_key` calls `_check_bindings` first. When a priority binding matches,
the event is consumed and neither `on_key` nor widget handlers fire. This means the dispatch
model is **structurally sound** — but the implementation has leaks.

## Audit Findings

### 1. Dead code: `ChatVimHandler` handles `ctrl+d` (tui_vim.py:428-429)

The `ChatVimHandler._handle_normal` method handles `ctrl+d` as half-page scroll, but `ctrl+d` is
also a `priority=True` BINDINGS entry. The binding always fires first and consumes the event.
The ChatVimHandler code path is unreachable.

**Status**: dead code, never executes. Not a bug (no double-scroll), but a maintenance hazard.

### 2. `ctrl+d` submits in Vim NORMAL mode (input pane)

When Vim is enabled and input pane is in NORMAL mode, `ctrl+d` still submits the editor content
because `action_submit_editor` only checks for `VimPane.CHAT`, not for NORMAL vs INSERT mode.

This violates the modal contract: in NORMAL mode, the user expects keys to be Vim commands or
pass-through, not app actions. Accidentally submitting half-edited text is a data-loss risk.

**Repro**: Toggle Vim on, type some text, press Escape (normal mode), press Ctrl+D → text submits.

### 3. `enter` inserts newline in Vim NORMAL mode (input pane)

`action_accept_completion_or_newline` unconditionally inserts a newline when no completion is
visible. In Vim NORMAL mode, this breaks the modal paradigm — Enter should either be a Vim
motion (next line) or be swallowed.

**Repro**: Toggle Vim on, press Escape (normal mode), press Enter → newline inserted in buffer.

### 4. `action_submit_editor` knows about Vim chat pane

The action handler special-cases `_vim.pane == VimPane.CHAT` to redirect `ctrl+d` from submit
to scroll. This couples the global submit binding to Vim state, making the binding non-orthogonal.

### 5. No emergent keybinding help

There is no way for a user to discover available keys. Top-tier TUIs (Helix, lazygit, k9s)
show context-sensitive keybinding panels. Our users must read source code or external docs.

### 6. Tab semantics invisible

Tab means three different things depending on state (completion cycling, pane cycling, menu
open). The status line shows mode/pane but doesn't indicate which behavior Tab currently has.

### 7. `super+c` copy conflicts with terminal

`Super+C` is `Ctrl+C` on most terminals, which sends SIGINT. The binding only works in
graphical terminal emulators that distinguish Super from Ctrl. On a raw TTY or SSH session,
`Super+C` is indistinguishable from `Ctrl+C` (interrupt).

## Comparison: Top-Tier TUI Keybinding Patterns

### What the best TUIs do

| TUI | Keybinding approach | Why it works |
|---|---|---|
| **Helix** | Single `keymap.toml`, modes as first-class, `?` shows context keys | One source of truth, discoverable, composable motions |
| **lazygit** | Contextual panels show available keys at all times, mode transitions clear | Zero-learning-curve: every key visible on screen |
| **k9s** | Vim navigation + contextual command aliases, `?` for help, `:` for commands | Vim muscle memory, discoverable commands |
| **broot** | Verb-driven: keys trigger verbs, `?` shows all, searchable | Consistent verb model, fuzzy-findable help |
| **Neovim** | Modal, composable (count+operator+motion), `:help` built-in | Gold standard for modal editing |

### Common patterns in Formula 1 TUIs

1. **Single dispatch table per mode** — not scattered across bindings, widget hooks, and app handlers
2. **Context-sensitive key help** — press `?` or see a footer bar with available keys
3. **Modal consistency** — if you commit to Vim, every key follows Vim semantics in that mode
4. **No overloaded keys without visual indication** — if Tab means different things, the UI shows which
5. **Composability** — count prefixes and operator+motion work everywhere, not just in some modes
6. **Gradual disclosure** — common keys shown, advanced keys behind `?`

### Where we fall short

| Issue | Top-tier practice | Our current state |
|---|---|---|
| Key discoverability | `?` shows all keys for current context | No help key; keys only in source/docs |
| Dispatch architecture | One keymap/mode | Three layers (BINDINGS, _on_key, on_key) |
| Modal purity | Keys follow mode contract strictly | `ctrl+d`/`enter` leak through in NORMAL mode |
| Dead code removal | Single source of truth | ChatVimHandler ctrl+d unreachable |
| Copy key | `y` (vim) or `ctrl+shift+c` (terminal-safe) | `super+c` (broken on raw TTY) |
| Status visibility | Footer bar with contextual keys | Vim status shows mode/pane only |

## Design Decisions

### D1: Keep `ctrl+d` and `enter` in BINDINGS, add Vim-mode guards

**Corrected** — the original spec proposed moving keys out of BINDINGS into `on_key`. This
doesn't work for `enter` because TextArea consumes it at the widget level before `on_key`
fires. And TextArea's native handling of `ctrl+d` (delete-right) would interfere.

Instead, keep both keys as priority bindings and add mode guards to their action handlers:

- `action_submit_editor`: when Vim NORMAL mode + input pane → return early (swallow)
- `action_accept_completion_or_newline`: when Vim NORMAL mode + input pane → return early (swallow)

This is a 2-line change. No router rewrite needed.

### D2: Keep `tab`/`shift+tab` in BINDINGS unchanged

Tab's three-way behavior (completions, pane cycling, menu open) is correct and well-tested.
There's no bug here — the action handler already checks Vim state. No changes needed.

### D3: Keep `super+c` as-is

The proposed `ctrl+shift+c` replacement cannot work: terminal emulators intercept
`ctrl+shift+c` for OS-level copy before Textual sees the key event. `super+c` works on
macOS and some Linux terminals where the WM doesn't capture Meta. Neither binding is
universally reliable — adding a second binding only adds dead code.

### D4: Remove dead `ctrl+d` from `ChatVimHandler`

`ChatVimHandler._handle_normal` handles `ctrl+d` at tui_vim.py:428-429, but the BINDINGS
priority binding always fires first and consumes the event. This code is unreachable.
Remove it.

### D5: Add `?` keybinding help panel (Phase 2)

Unchanged from original spec — deferred to a follow-up phase.

### D6: Removed — `ctrl+shift+c` rejected

See D3. The proposed `ctrl+shift+c` replacement is infeasible — OS-level interception.

### D7: Removed — unified key router over-engineering

The three-layer dispatch is structurally correct for Textual 8.2.7. Fixing the two mode
leaks (ctrl+d, enter) with guard clauses in their action handlers is a 2-line change.
A full router rewrite for Phase 1 would risk regressions with no benefit.

## Requirements

### R1: `ctrl+d` does not submit in Vim NORMAL mode (input pane)

- Given Vim enabled, input pane focused, NORMAL mode
- When `ctrl+d` is pressed
- Then: key is swallowed, nothing happens (no submit, no text insertion)

### R2: `ctrl+d` submits in INSERT mode (input pane)

- Given Vim enabled, input pane focused, INSERT mode
- When `ctrl+d` is pressed
- Then: editor content is submitted (current behavior preserved)

### R3: `ctrl+d` scrolls in chat pane Vim mode

- Given Vim enabled, chat pane focused, NORMAL mode
- When `ctrl+d` is pressed
- Then: chat scrolls down half page (current behavior preserved — BINDINGS priority
  captures ctrl+d → `action_submit_editor` → chat pane check → `scroll_page_down()`)

### R4: `enter` does not insert newline in Vim NORMAL mode (input pane)

- Given Vim enabled, input pane focused, NORMAL mode
- When `Enter` is pressed
- Then: key is swallowed, nothing happens

### R5: `enter` inserts newline in INSERT mode and Vim-off mode

- Given Vim off, or Vim INSERT mode, input focused
- When `Enter` is pressed
- Then: newline inserted in editor (current behavior preserved)

### R6: `enter` accepts completion when menu visible

- Given completion menu visible
- When `Enter` is pressed
- Then: highlighted completion is accepted (current behavior preserved)

### R7: Dead `ctrl+d` removed from `ChatVimHandler`

- `ChatVimHandler._handle_normal` no longer handles `ctrl+d`
- The binding already works through BINDINGS → `action_submit_editor` → chat pane check
- Code removal only — no behavioral change

### R8: No copy binding change

- `super+c` kept as-is. `ctrl+shift+c` is intercepted by terminal emulators.

### R9: `?` key opens keybinding help (Phase 2 — deferred)

Unchanged. Not implemented in Phase 1.

### R10: No regression in existing TUI behavior

- All 72 existing TUI/Vim tests pass
- Completion cycling works as before
- Tab pane cycling works as before
- Vim off mode is completely unaffected
- Submit via `alt+enter` and `super+enter` works as before

### R11: `ctrl+u` in chat pane preserved

+- `ctrl+u` is NOT in BINDINGS, flows through `on_key` → `ChatVimHandler`
+- No changes touch this path — guaranteed preserved

## Non-Goals

+- Full Vim emulation (macros, marks, registers, ex commands)
+- Character-level chat visual selection over rendered Markdown
+- Auto-generated binding help (static text only for Phase 2)
+- Persistent footer bar showing contextual keys (deferred)
+- Search-based transcript navigation (`/`, `n`, `N`)
+- Changing the Tab pane-cycling semantics
+- Changing the Enter/Submit separation design

## Implementation Plan

### Phase 1: Fix mode leaks and remove dead code

**Three changes, ~5 lines of code.**

#### Change 1: Guard `action_submit_editor` against NORMAL mode (tui.py:382)

Insert before the existing `if self._vim.enabled and self._vim.pane == VimPane.CHAT:` check:
```python
    if self._vim.enabled and self._vim.pane == VimPane.INPUT and self._vim.mode == VimMode.NORMAL:
        return
```

#### Change 2: Guard `action_accept_completion_or_newline` against NORMAL mode (tui.py:468)

Insert after the completion-visible check, before the `insert("\n")` call:
```python
    if self._vim.enabled and self._vim.pane == VimPane.INPUT and self._vim.mode == VimMode.NORMAL:
        return
```

#### Change 3: Remove dead `ctrl+d` from ChatVimHandler (tui_vim.py:428-429)

Delete these two lines from `ChatVimHandler._handle_normal`:
```python
        if key == "ctrl+d":
            chat.scroll_page_down()
            return True
```

### Phase 2 (future): `?` keybinding help panel

| File | Change |
|---|---|
| `harness_poc/tui.py` | Add `?` binding (non-priority). Static help content. |
| `tests/repl/test_tui.py` | Add tests for help open/dismiss. |

## Key Dispatch (unchanged in Phase 1)

No architectural changes. The dispatch model stays:

```
App._on_key
  → _check_bindings (BINDINGS priority)   ← ctrl+d, enter, tab, F2 live here
  → dispatch_key
      → VimTextArea._on_key               ← input pane Vim single-char keys
      → ChatApp.on_key                    ← chat pane Vim keys
```

BINDINGS remain:
```python
BINDINGS = [
    Binding("super+c", "copy_smart", ...),                     # unchanged
    Binding("super+y", "copy_last_response", ...),             # unchanged
    Binding("ctrl+d", "submit_editor", ...),                   # unchanged — guard added
    Binding("alt+enter", "submit_editor", ...),                # unchanged
    Binding("super+enter", "submit_editor", ...),              # unchanged
    Binding("tab", "cycle_completion_forward", ...),           # unchanged
    Binding("shift+tab", "cycle_completion_backward", ...),    # unchanged
    Binding("enter", "accept_completion_or_newline", ...),     # unchanged — guard added
    Binding("f2", "toggle_vim", ...),                          # unchanged
]
```

## Verification

### Automated

```bash
# Existing tests must pass
uv run pytest tests/repl/test_tui.py tests/repl/test_tui_vim.py -v

# New tests for mode guards
uv run pytest tests/repl/test_tui.py -k "normal_mode" -v
```

### Manual smoke test

1. Start TUI: `uv run harness-poc`
2. Type text, press `Ctrl+D` → submits (Vim off)
3. Press `Enter` → inserts newline (Vim off)
4. Press `F2` → Vim on, INSERT mode
5. Type text, press `Enter` → inserts newline ✓
6. Press `Escape` → NORMAL mode
7. Press `Enter` → **nothing happens** (no newline leak) ✓
8. Press `Ctrl+D` → **nothing happens** (no submit leak) ✓
9. Press `Tab` → switches to chat pane (NORMAL chat)
10. Press `Ctrl+D` → scrolls half page down (once) ✓
11. Press `i` → back to input, INSERT mode
12. Press `Ctrl+D` → submits ✓
13. Press `F2` → Vim off

## Review Notes

+- Initial draft 2026-06-13 based on audit of current implementation vs. design spec
+- **Corrected 2026-06-13** after subagent review: enter cannot be handled in `on_key` (TextArea
  consumes it first); `ctrl+shift+c` infeasible (OS interception); tab stays in BINDINGS.
  Fix reduced to mode guards in existing action handlers + dead code removal.
+- No changes to REPL, skills, LLM runtime, or blackboard
+- All changes confined to `tui.py`, `tui_vim.py`, and their tests
