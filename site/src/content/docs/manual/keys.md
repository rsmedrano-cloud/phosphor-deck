---
title: Keys
sidebar:
  order: 6
---


zellij runs in **locked mode**: every key goes to the program in the pane,
except these.

| key | action |
|---|---|
| Alt-n | new tab (the + menu) in the folder of the pane you're in |
| Alt-r | edit this tab: unlock, change, then save or put it back |
| Alt-j | a note or todo from here: NOTES shows which tab it came from |
| Alt-g | take and give back zellij's controls (same key) |
| Alt-1 … Alt-9 | go to a tab, in the order of your profile |
| tap | a tab to switch, a pane to focus it |
| + (tab bar) | new tab: a shell here or on a machine, an assistant, files... |
| select (drag) | copies to the clipboard of every device on the deck |
| phosphor clip F | a file or a pipe onto that clipboard (up to ~70 KB) |
| Alt-← ↑ ↓ → | move between panes; left/right past the edge: the next tab |
| Alt-z | zoom — the focused pane takes the whole tab |
| Alt-x · Ctrl-q | leave the deck — the session keeps running |
| exit · q | a tab asks before closing: Enter opens it again, x closes it |
| Ctrl-z | harmless: a pane it stops wakes up by itself in a few seconds |
| Alt-f | disabled (floating panes wedge zellij) |
| Ctrl-p n / x | new pane / close it |
| Ctrl-t n / r | new tab / rename it |
| Ctrl-n | resize (hjkl) |

In locked mode only these are live. Everything else,
Ctrl-g included, goes straight to the tool inside.
--- with the controls taken (Alt-g) ---

## Editing a tab

Tabs are locked: no pane is added or closed by accident. To change one on
purpose, **Alt-r** (on a phone, the **EDIT** key). Every step works with a
key, a click or a tap: each action is a row of its own.

1. **start editing** unlocks the tab (a ✎ marks it in the tab bar). Resize
   by dragging a border, or Ctrl-n and the arrows; Ctrl-p n / x add and
   close panes.
2. **Alt-r** again shows what changed (`ctop → lazydocker`, `45% → 55%`) and
   what you can do with the pane under that screen:
   **s** save the tab into your profile · **d** put it back the way the
   profile has it · **r** swap the pane's program for anything the + menu or
   the store has · **b** / **v** split it (a new pane below / beside) ·
   **x** close it · **e** keep editing.

One thing zellij doesn't let us lock: dragging a border resizes a pane even
while the tab is locked. `phosphor restart` (or Alt-r, then d) brings back the
sizes your profile has.

A tab that isn't in the profile yet (opened with +) is added when you save.
A tab from `tabs.d` (see profile) has no **s**: it names the file instead,
since saving there would fork it from whoever you got it from.
Editing changes the mode for every screen looking at the deck.

## Your own keys

Every deck key can be changed: `phosphor shortcuts` (or **c** in the DECK
tab) lists them; pick one, press the new key, and it works right away. It
warns when the key is taken by another deck key or by a tool (matterhorn,
the shell). Backspace turns one off. A key the deck already uses never
reaches that screen: free it first.

They're kept in `[keys]` in your profile (see profile), so an update never
resets them. `phosphor gen` writes them into zellij's config.kdl between two
marker lines and touches nothing else there: binds of your own can go
anywhere outside the markers. A config.kdl of your own without the markers
is left alone; `phosphor shortcuts --kdl` prints the block to paste inside
its `keybinds { }`.

The phone kit's EDIT, ZOOM and EXIT keys send whatever `[keys]` says (run the
kit again after changing them).

## When a program ends

Every program runs through `phosphor run`. When it ends (`exit`, `q`, a
crash) the pane doesn't vanish or quietly restart: it says so in color and
asks. **Enter** opens it again, **x** closes the tab. A mistyped exit costs
one key. In ssh tabs a dropped link reconnects by itself; a program that isn't
installed says so. If that tab is kept in your profile (so it comes back
after every restart) and this was its last program, a third choice shows:
**f** closes it and forgets it, out of the profile for good. `phosphor tabs`
does the same for any kept tab. A program that froze (the pane changed size and it didn't
answer or do anything for 20 seconds) is closed and the pane says "stopped
responding": Enter opens it again.

## Tapping

Tap a tab to switch, a pane to focus it; `+` in the tab bar opens the new-tab
menu. On phones, taps go to the deck, so the keyboard needs its own key (the
phone kit adds KEYBOARD, EDIT, ZOOM and EXIT).

The DECK tab lists the keys of every installed tool, next to the panel with
every phosphor action (a key or a tap each).
